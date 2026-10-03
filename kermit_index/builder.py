"""Deterministic static metadata extraction from explicit admitted files only."""

import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re


SCHEMA_VERSION = 1
INDEXER_VERSION = "1.0.0"
ENTITY_TYPES = frozenset(("subsystem", "page", "widget", "module", "symbol", "api_operation", "store", "data_artifact", "transformation", "metric", "job_worker", "integration", "test_contract", "document", "conflict"))
REL_TYPES = frozenset(("owns", "calls", "reads", "writes", "renders", "exposes", "handles", "imports", "depends_on", "generates", "caches", "processes", "tests", "documents", "supersedes", "conflicts_with"))
DENIED_PARTS = frozenset((".git", "node_modules", "dist", "build", "out", "reports", "coverage", "covers", "cache", "caches", "__pycache__", ".vite", ".vitest", "backups", "raw", "imports", "private", "models", "audio", "media", "data", "tmp"))
DENIED_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".log", ".bak", ".zip", ".tar", ".gz", ".png", ".jpg", ".jpeg", ".pdf", ".mp3", ".lock", "-wal", "-shm", "-journal", ".tmp", ".swp")
ALLOWED_EXT = {"documentation": {".md"}, "source": {".py", ".js", ".html"}, "test": {".py", ".js"}}
CORE_NAMES = ("manifest.json", "sources.jsonl", "entities.jsonl", "relationships.jsonl", "documents.jsonl", "conflicts.jsonl")
FINDING_CATEGORIES = frozenset(("FACTUAL_CONFLICT", "DOCUMENTATION_DRIFT", "TEST_COVERAGE_GAP",
                                "UNKNOWN_BEHAVIOR", "AMBIGUOUS_SEMANTICS", "DISPLAY_OR_IMPLEMENTATION_QUIRK"))
MAX_ARTIFACT_BYTES = 20_000_000
PILOTS = {"quote": "Random Quote", "finance": "Finance / Budget", "language-learning": "Language Learning", "weather": "Weather"}
EXPANSION = {"cleaning": "Cleaning", "reading": "Reading", "todo": "Todo board"}
B2 = {"dashboard": "Main dashboard", "settings": "Settings", "central-api": "Central API and static security"}
B3 = {"habits-app": "Habits App", "habits-summary": "Legacy Habits summary",
      "habits-timeline": "Habits Timeline", "self-care": "Self-care"}
B4A = {"weight-steps": "Weight and steps", "diet": "Diet", "sleep": "Sleep"}
B4B = {"mental-health": "Mental Health", "sensors": "Sensors", "ble-collector": "BLE collector"}
PACKS = {**PILOTS, **EXPANSION, **B2, **B3, **B4A, **B4B}
PILOT_WIDGETS = {"quote": "quote", "budget": "finance", "bills": "finance", "language-learning": "language-learning", "weather": "weather", "cleaning": "cleaning", "reading": "reading", "todo": "todo", "habits-app": "habits-app", "habits": "habits-summary", "habits-timeline": "habits-timeline", "self-care": "self-care", "weight-cut": "weight-steps", "diet": "diet", "mental-health": "mental-health", "sensors": "sensors"}


class IndexErrorClosed(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, relative, group, max_bytes):
    if not isinstance(relative, str) or not relative or "\\" in relative or "%" in relative or "\x00" in relative:
        raise IndexErrorClosed("invalid admitted path")
    p = PurePosixPath(relative)
    if p.is_absolute() or len(relative) > 240 or any(x in (".", "..", "") for x in relative.split("/")) or re.match(r"^[A-Za-z]:", relative):
        raise IndexErrorClosed(f"unsafe admitted path: {relative}")
    parts = [x.lower() for x in p.parts]
    name = parts[-1]
    if any((x in DENIED_PARTS and not (x == "audio" and relative == "js/language/audio/browser-speech.js")) or x.startswith(".tmp-") or any(word in x for word in ("secret", "credential", "token", "oauth", "chatgpt")) for x in parts) or name.startswith(".env") or name.startswith(".") or any(name.endswith(s) for s in DENIED_SUFFIXES) or any(x in name for x in ("private", "apikey", "api-key", "api_key")):
        raise IndexErrorClosed(f"denied admitted path: {relative}")
    if group not in ALLOWED_EXT or p.suffix.lower() not in ALLOWED_EXT[group]:
        raise IndexErrorClosed(f"denied format/group: {relative}")
    current = root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise IndexErrorClosed(f"symlink/junction denied: {relative}")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise IndexErrorClosed(f"path escape or non-file: {relative}")
    if resolved.stat().st_size > max_bytes:
        raise IndexErrorClosed(f"oversized admitted source: {relative}")
    return resolved


def load_manifest(root, manifest):
    # Configuration is trusted only from the caller's fixed manifest path; its entries are still validated.
    spec = json.loads(manifest.read_text(encoding="utf-8"))
    if spec.get("schemaVersion") != SCHEMA_VERSION or not isinstance(spec.get("entries"), list) or not isinstance(spec.get("defaults"), dict):
        raise IndexErrorClosed("invalid admission schema")
    seen = set()
    entries = []
    for item in spec["entries"]:
        if not isinstance(item, dict) or set(item) != {"path", "group", "subsystem"}:
            raise IndexErrorClosed("admission entry fields invalid")
        path, group, subsystem = item["path"], item["group"], item["subsystem"]
        if path in seen or subsystem not in set(PACKS) | {"shared"} or group not in spec["defaults"]:
            raise IndexErrorClosed("duplicate or invalid admission entry")
        seen.add(path)
        policy = spec["defaults"][group]
        if not isinstance(policy.get("maxBytes"), int) or not 0 < policy["maxBytes"] <= 2_000_000 or policy.get("privacyClassification") not in ("public_project_knowledge", "internal_implementation") or policy.get("contentMode") != ("sections" if group == "documentation" else "metadata_only") or policy.get("parserMode") != ("markdown" if group == "documentation" else "static"):
            raise IndexErrorClosed("invalid admission policy")
        file_path = safe_path(root, path, group, policy["maxBytes"])
        entries.append((item, policy, file_path))
    return spec, sorted(entries, key=lambda x: x[0]["path"])


def read_source(path, limit):
    # Bound again at read time. Unknown binary data fails before parser dispatch.
    with path.open("rb") as file:
        raw = file.read(limit + 1)
    if len(raw) > limit or b"\x00" in raw:
        raise IndexErrorClosed(f"oversized or binary admitted source: {path.name}")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IndexErrorClosed(f"non-UTF-8 admitted source: {path.name}") from exc
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if sum(c in "\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f" for c in content) > 0:
        raise IndexErrorClosed(f"binary control data: {path.name}")
    return raw, content


def stable_id(kind, key):
    if kind not in ENTITY_TYPES or not isinstance(key, str) or not key:
        raise IndexErrorClosed("invalid entity identity")
    return f"{kind}:{key}"


def section_slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "section"


def line_ref(source, locator):
    return {"sourceId": source["id"], "path": source["path"], "fingerprint": source["sha256"], "locator": locator}


def make_entity(kind, key, name, source, locator, **fields):
    return {"schemaVersion": SCHEMA_VERSION, "id": stable_id(kind, key), "type": kind, "displayName": name, "sourceClass": source["sourceClass"], "privacyClassification": source["privacyClassification"], "sourceReferences": [line_ref(source, locator)], "provenance": [line_ref(source, locator)], **fields}


def extract_sections(content):
    lines = content.splitlines()
    starts = [(i + 1, len(m.group(1)), m.group(2).strip()) for i, line in enumerate(lines) if (m := re.match(r"^(#{1,6})\s+(.+?)\s*$", line))]
    if not starts:
        starts = [(1, 1, "Document")]
    result = []
    seen = Counter()
    for position, (start, level, title) in enumerate(starts):
        # A section owns only its own lines up to its first child heading.
        own_end = starts[position + 1][0] - 1 if position + 1 < len(starts) else len(lines)
        body = "\n".join(lines[start - 1:own_end])
        slug = section_slug(title)
        seen[slug] += 1
        locator = f"heading:{slug}:{seen[slug]}"
        result.append((title, locator, start, own_end, body[:12000], len(body) > 12000))
    return result


def add_relationship(out, relation, origin, target, evidence):
    if relation not in REL_TYPES:
        raise IndexErrorClosed("unknown relation")
    key = f"{relation}|{origin}|{target}|{evidence['sourceId']}|{evidence['locator']}"
    out[key] = {"schemaVersion": SCHEMA_VERSION, "id": "relationship:" + digest(key.encode())[:24], "type": relation, "from": origin, "to": target, "provenance": [evidence]}


def extract_python(text, source, entities, relations):
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise IndexErrorClosed(f"Python parse failed: {source['path']}:{exc.lineno}") from exc
    module_id = stable_id("module", source["path"])
    extracted = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [(node.name, node)]
            if isinstance(node, ast.ClassDef):
                names += [(f"{node.name}.{child.name}", child) for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for name, child in names:
                if source["path"] == "server.py" and not re.search(r"budget|finance|language", name, re.I):
                    continue
                if extracted >= 250:
                    break
                locator = f"symbol:{name}:L{child.lineno}-L{getattr(child, 'end_lineno', child.lineno)}"
                entity = make_entity("symbol", f"{source['path']}::{name}", name, source, locator, owningSubsystem=source["subsystem"], repositoryPath=source["path"], lineStart=child.lineno, lineEnd=getattr(child, "end_lineno", child.lineno), symbolKind="class" if isinstance(child, ast.ClassDef) else "function")
                entities[entity["id"]] = entity
                add_relationship(relations, "owns", module_id, entity["id"], line_ref(source, locator))
                extracted += 1


JS_DECL = re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function|class|const)\s+([A-Za-z_$][\w$]*)\b")
IMPORT = re.compile(r"(?:import\s+(?:[^;]*?\s+from\s+)?|import\s*\(|require\s*\()\s*['\"]([^'\"]+)['\"]")
WIDGET = re.compile(r"data-widget\s*=\s*['\"]([^'\"]+)['\"]")
ID_ATTR = re.compile(r"\bid\s*=\s*['\"]([A-Za-z][\w-]*)['\"]")
SCRIPT_SRC = re.compile(r"<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", re.I)
ROUTE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+`?(/api/[A-Za-z0-9_{}/*:.-]+)")
PATH_REF = re.compile(r"(?<![\w/])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|js|html|md)\b")


def extract_js(text, source, entities, relations):
    module_id = stable_id("module", source["path"])
    for number, line in enumerate(text.splitlines(), 1):
        match = JS_DECL.match(line)
        if match:
            name = match.group(1)
            locator = f"symbol:{name}:L{number}"
            entity = make_entity("symbol", f"{source['path']}::{name}", name, source, locator, owningSubsystem=source["subsystem"], repositoryPath=source["path"], lineStart=number)
            entities[entity["id"]] = entity
            add_relationship(relations, "owns", module_id, entity["id"], line_ref(source, locator))


def extract_html(text, source, entities, relations, admitted):
    page_id = stable_id("page", source["path"])
    page = make_entity("page", source["path"], source["path"], source, "file", owningSubsystem=source["subsystem"], repositoryPath=source["path"], implementationStatus="current")
    entities[page_id] = page
    for number, line in enumerate(text.splitlines(), 1):
        for script in SCRIPT_SRC.findall(line):
            target = script.lstrip("/")
            if target in admitted and target.endswith(".js") and admitted[target]["sourceClass"] == "project_source":
                add_relationship(relations, "depends_on", page_id, stable_id("module", target), line_ref(source, f"script-src:{target}:L{number}"))
        for widget in WIDGET.findall(line):
            if widget in PILOT_WIDGETS:
                widget_id = stable_id("widget", widget)
                if widget_id not in entities:
                    entities[widget_id] = make_entity("widget", widget, widget, source, f"data-widget:{widget}:L{number}", owningSubsystem=PILOT_WIDGETS[widget], implementationStatus="current", repositoryPath=source["path"])
                add_relationship(relations, "renders", page_id, widget_id, line_ref(source, f"data-widget:{widget}:L{number}"))


def build_data(root, manifest):
    spec, admissions = load_manifest(root, manifest)
    source_records = []
    contents = {}
    admitted = {}
    for item, policy, path in admissions:
        raw, body = read_source(path, policy["maxBytes"])
        rel = item["path"]
        record = {"schemaVersion": SCHEMA_VERSION, "id": f"source:{rel}", "path": rel, "sha256": digest(raw), "sourceClass": policy["sourceClass"], "expectedRole": policy["expectedRole"], "privacyClassification": policy["privacyClassification"], "parserMode": policy["parserMode"], "contentMode": policy["contentMode"], "maxBytes": policy["maxBytes"], "sizeBytes": len(raw), "subsystem": item["subsystem"], "indexerVersion": INDEXER_VERSION, "provenance": [{"admissionManifest": "kermit_index/admission.json", "path": rel}]}
        source_records.append(record)
        admitted[rel] = record
        contents[rel] = body
    entities = {}
    relations = {}
    documents = []
    conflicts = []
    pack_slugs = [slug for slug in PACKS if f"docs/kermit/knowledge/subsystems/{slug}.md" in admitted]
    for slug in pack_slugs:
        label = PACKS[slug]
        source = admitted[f"docs/kermit/knowledge/subsystems/{slug}.md"]
        entities[stable_id("subsystem", slug)] = make_entity("subsystem", slug, label, source, "heading:identity-and-verification:1", owningSubsystem=slug, status="current", implementationStatus="verified_in_L1")
    for source in source_records:
        rel = source["path"]
        body = contents[rel]
        if rel.endswith(".md"):
            doc = make_entity("document", rel, rel, source, "file", owningSubsystem=source["subsystem"], status="reviewed" if "knowledge/subsystems/" in rel else "documented", repositoryPath=rel)
            entities[doc["id"]] = doc
            for title, locator, start, end, section, truncated in extract_sections(body):
                unit = {"schemaVersion": SCHEMA_VERSION, "id": f"document_unit:{rel}#{locator}", "parentDocument": doc["id"], "heading": title, "locator": locator, "lineStart": start, "lineEnd": end, "content": section, "truncated": truncated, "sourceStatus": doc["status"], "subsystem": source["subsystem"], "sourceFingerprint": source["sha256"], "provenance": [line_ref(source, locator)]}
                documents.append(unit)
            if source["subsystem"] in pack_slugs:
                add_relationship(relations, "documents", doc["id"], stable_id("subsystem", source["subsystem"]), line_ref(source, "file"))
        elif source["sourceClass"] == "project_test":
            entity = make_entity("test_contract", rel, rel, source, "file", owningSubsystem=source["subsystem"], repositoryPath=rel, implementationStatus="test_source_present")
            entities[entity["id"]] = entity
        else:
            entity = make_entity("module", rel, rel, source, "file", owningSubsystem=source["subsystem"], repositoryPath=rel, implementationStatus="current")
            entities[entity["id"]] = entity
            if rel.endswith(".py"):
                extract_python(body, source, entities, relations)
            elif rel.endswith(".js"):
                extract_js(body, source, entities, relations)
            elif rel.endswith(".html"):
                extract_html(body, source, entities, relations, admitted)
    # Imports are linked only when a literal import resolves exactly to an admitted module.
    for source in source_records:
        path = source["path"]
        if stable_id("module", path) not in entities:
            continue
        if path.endswith(".py"):
            tree = ast.parse(contents[path])
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    target = name.replace(".", "/") + ".py"
                    if target in admitted and stable_id("module", target) in entities:
                        add_relationship(relations, "imports", stable_id("module", path), stable_id("module", target), line_ref(source, f"L{node.lineno}"))
        elif path.endswith(".js"):
            for number, line in enumerate(contents[path].splitlines(), 1):
                for specifier in IMPORT.findall(line):
                    if not specifier.startswith("."):
                        continue
                    target = str(PurePosixPath(path).parent.joinpath(specifier))
                    target = os.path.normpath(target).replace("\\", "/")
                    if not target.endswith(".js"):
                        target += ".js"
                    if target in admitted and stable_id("module", target) in entities:
                        add_relationship(relations, "imports", stable_id("module", path), stable_id("module", target), line_ref(source, f"L{number}"))
    # Relationships between each reviewed pack and precisely named, admitted source paths.
    for slug in pack_slugs:
        path = f"docs/kermit/knowledge/subsystems/{slug}.md"
        source = admitted[path]
        doc_id = stable_id("document", path)
        for number, line in enumerate(contents[path].splitlines(), 1):
            for target in set(PATH_REF.findall(line)) & admitted.keys():
                if target == path:
                    continue
                target_type = "document" if target.endswith(".md") else "test_contract" if target.startswith("tests/") else "module"
                target_id = stable_id(target_type, target)
                if target_id in entities:
                    add_relationship(relations, "documents", doc_id, target_id, line_ref(source, f"L{number}"))
                    if target_type == "test_contract":
                        add_relationship(relations, "tests", target_id, stable_id("subsystem", slug), line_ref(source, f"L{number}"))
                    if target_type == "module" and admitted[target]["subsystem"] == slug:
                        add_relationship(relations, "owns", stable_id("subsystem", slug), target_id, line_ref(source, f"L{number}"))
            for method, route in ROUTE.findall(line):
                key = f"{method}:{route}"
                api_id = stable_id("api_operation", key)
                if api_id not in entities:
                    entities[api_id] = make_entity("api_operation", key, f"{method} {route}", source, f"L{number}", owningSubsystem=slug, route=route, method=method, implementationStatus="documented_in_L1")
                add_relationship(relations, "documents", doc_id, api_id, line_ref(source, f"L{number}"))
                add_relationship(relations, "owns", stable_id("subsystem", slug), api_id, line_ref(source, f"L{number}"))
                add_relationship(relations, "exposes", stable_id("subsystem", slug), api_id, line_ref(source, f"L{number}"))
                if "server.py" in line:
                    add_relationship(relations, "handles", stable_id("module", "server.py"), api_id, line_ref(source, f"L{number}"))
        add_relationship(relations, "owns", stable_id("subsystem", slug), doc_id, line_ref(source, "file"))
    # L1 table rows yield bounded named concepts; fields remain documented rather than asserted from code.
    concept_sections = {"Metrics and calculations": "metric", "Persistence and source of truth": "data_artifact", "Jobs and recovery": "job_worker", "Jobs, integrations, dependencies, failure and recovery": "job_worker", "Data flow": "transformation", "Data flow and transformations": "transformation", "Integrations, failure and privacy": "integration"}
    for slug in pack_slugs:
        path = f"docs/kermit/knowledge/subsystems/{slug}.md"
        source = admitted[path]
        heading = ""
        for number, line in enumerate(contents[path].splitlines(), 1):
            if line.startswith("## "):
                heading = line[3:].strip()
            flow_match = re.match(r"^(\d+)\.\s+(.+)$", line) if heading in ("Data flow", "Data flow and transformations") else None
            if flow_match:
                label = re.sub(r"[`*]", "", flow_match.group(2).split(".", 1)[0]).strip()[:72]
                key = f"{slug}:step-{flow_match.group(1)}"
                eid = stable_id("transformation", key)
                if label and eid not in entities:
                    entities[eid] = make_entity("transformation", key, label, source, f"L{number}", owningSubsystem=slug, implementationStatus="documented_in_L1")
                    add_relationship(relations, "owns", stable_id("subsystem", slug), eid, line_ref(source, f"L{number}"))
            if heading == "Persistence and source of truth" and line.startswith("|") and not line.startswith("| ---"):
                cells = [c.strip().strip("`*") for c in line.strip().strip("|").split("|")]
                if len(cells) >= 3 and cells[1] not in ("Owner", "") and cells[0] not in ("Artifact/entity", "Artifact/entity | Owner") and "secret" not in (cells[0] + cells[2]).lower():
                    owner = cells[1].split(".", 1)[0].split(" and ", 1)[0].strip("`* ")
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", owner):
                        sid = stable_id("store", f"{slug}:{owner}")
                        if sid not in entities:
                            entities[sid] = make_entity("store", f"{slug}:{owner}", owner, source, f"L{number}", owningSubsystem=slug, implementationStatus="documented_in_L1")
                            add_relationship(relations, "owns", stable_id("subsystem", slug), sid, line_ref(source, f"L{number}"))
            kind = concept_sections.get(heading)
            if not kind or not line.startswith("|") or line.startswith("| ---"):
                continue
            cells = [c.strip().strip("`*") for c in line.strip().strip("|").split("|")]
            name = cells[0] if cells else ""
            if not name or name.lower() in ("metric", "value", "artifact/entity", "provider", "trigger and queue", "input", "surface") or len(name) > 90 or name.lower().startswith(("none", "not applicable")):
                continue
            if kind == "data_artifact" and ("secret" in line.lower() or "token" in line.lower() or "credential" in line.lower()):
                continue
            if kind == "data_artifact" and ("data/" in name or name.endswith(".sqlite")):
                # Private paths are represented only by a named role in L1, never as index paths.
                name = re.sub(r"`?data/[^`\s|]+`?", "private runtime artifact", name)
            key = f"{slug}:{section_slug(name)}"
            if kind == "data_artifact":
                key += ":" + digest(cells[0].encode("utf-8"))[:12]
            eid = stable_id(kind, key)
            if eid not in entities:
                extra = {}
                if kind == "data_artifact":
                    role_match = re.search(r"\b(canonical|cache|generated|raw archive|backup|migration input|legacy|browser-only)\b", " ".join(cells[1:]), re.I)
                    if role_match:
                        extra["storageRole"] = role_match.group(1).lower()
                entities[eid] = make_entity(kind, key, name, source, f"L{number}", owningSubsystem=slug, implementationStatus="documented_in_L1", **extra)
                add_relationship(relations, "owns", stable_id("subsystem", slug), eid, line_ref(source, f"L{number}"))
                if kind == "data_artifact" and len(cells) > 1:
                    owner = cells[1].split(".", 1)[0].split(" and ", 1)[0].strip("`* ")
                    store_id = stable_id("store", f"{slug}:{owner}")
                    if store_id in entities:
                        add_relationship(relations, "owns", store_id, eid, line_ref(source, f"L{number}"))
        if slug == "language-learning":
            for number, line in enumerate(contents[path].splitlines(), 1):
                if "LanguageJobManager" in line and "worker" in line.lower():
                    eid = stable_id("job_worker", "language-learning:LanguageJobManager")
                    entities[eid] = make_entity("job_worker", "language-learning:LanguageJobManager", "LanguageJobManager", source, f"L{number}", owningSubsystem=slug, implementationStatus="documented_in_L1")
                    add_relationship(relations, "owns", stable_id("subsystem", slug), eid, line_ref(source, f"L{number}"))
                    break
    # Reviewed side references are exact admitted spans, never model-selected paths.
    side_spec = json.loads((root / "kermit_index/finding_sides.json").read_text(encoding="utf-8"))
    expected_codes = {"Q-01", "W-01", "W-02", "F-01", "F-02", "F-03", "F-04", "L-01"}
    if side_spec.get("schemaVersion") != 1 or set(side_spec.get("findings", {})) != expected_codes:
        raise IndexErrorClosed("incomplete finding side metadata")
    def reviewed_side(raw_side):
        if not isinstance(raw_side.get("description"), str) or not raw_side["description"].strip() or not isinstance(raw_side.get("refs"), list):
            raise IndexErrorClosed("invalid reviewed finding side")
        refs = []
        for ref in raw_side["refs"]:
            path = ref["path"]
            if path not in admitted:
                raise IndexErrorClosed(f"finding side is not admitted: {path}")
            lines = contents[path].splitlines()
            first, last = ref["start"], ref["end"]
            if (not isinstance(first, int) or not isinstance(last, int) or first < 1
                    or last < first or last - first >= 24 or last > len(lines)):
                raise IndexErrorClosed(f"invalid finding side span: {path}")
            excerpt = "\n".join(lines[first - 1:last])
            if ref["anchor"] not in excerpt or len(excerpt.encode("utf-8")) > 1600:
                raise IndexErrorClosed(f"finding side anchor or byte limit failed: {path}")
            source = admitted[path]
            refs.append({"path": path, "sourceId": source["id"], "sourceSha256": source["sha256"],
                         "lineStart": first, "lineEnd": last, "anchor": ref["anchor"]})
        return {"description": raw_side["description"], "expectedSourceRefs": refs}
    # Eight registered findings retain the reviewed L1 discovery record.
    gap_source = admitted["docs/kermit/knowledge/GAPS_AND_CONFLICTS.md"]
    for match in re.finditer(r"(?ms)^## (Q-01|W-01|W-02|F-01|F-02|F-03|F-04|L-01)\s*$\n(.*?)(?=^## |\Z)", contents[gap_source["path"]]):
        code, section = match.groups()
        line_no = contents[gap_source["path"]][:match.start()].count("\n") + 1
        fields = dict(re.findall(r"(?m)^- \*\*(.+?):\*\*\s*(.*)$", section))
        slug = {"Q": "quote", "W": "weather", "F": "finance", "L": "language-learning"}[code[0]]
        entity = make_entity("conflict", code, code, gap_source, f"heading:{code}:1", owningSubsystem=slug, findingType=fields.get("Type"), description=fields.get("Description"), impact=fields.get("Impact on future Kermit answers"), blocksPhase3=fields.get("Blocks Phase 3?") == "Yes", status="known_gap_or_conflict")
        entities[entity["id"]] = entity
        side = side_spec["findings"][code]
        if side.get("category") not in FINDING_CATEGORIES:
            raise IndexErrorClosed("invalid finding category")
        conflicts.append({"schemaVersion": SCHEMA_VERSION, "id": entity["id"], "subsystem": slug,
                          "type": fields.get("Type"), "category": side["category"],
                          "sideA": reviewed_side(side["sideA"]), "sideB": reviewed_side(side["sideB"]),
                          "description": fields.get("Description"), "impact": fields.get("Impact on future Kermit answers"),
                          "blocksPhase3": fields.get("Blocks Phase 3?") == "Yes", "provenance": [line_ref(gap_source, f"L{line_no}")]})
        add_relationship(relations, "documents", stable_id("document", gap_source["path"]), entity["id"], line_ref(gap_source, f"L{line_no}"))
        add_relationship(relations, "owns", stable_id("subsystem", slug), entity["id"], line_ref(gap_source, f"L{line_no}"))
    if {c["id"] for c in conflicts} != {stable_id("conflict", x) for x in ("Q-01", "W-01", "W-02", "F-01", "F-02", "F-03", "F-04", "L-01")}:
        raise IndexErrorClosed("incomplete L1 findings register")
    return {"manifest.json": {"schemaVersion": SCHEMA_VERSION, "indexerVersion": INDEXER_VERSION, "policy": spec["sourcePolicy"], "sources": [{"path": s["path"], "sourceClass": s["sourceClass"], "expectedRole": s["expectedRole"], "subsystem": s["subsystem"], "privacyClassification": s["privacyClassification"], "parserMode": s["parserMode"], "contentMode": s["contentMode"], "maxBytes": s["maxBytes"]} for s in source_records]}, "sources.jsonl": source_records, "entities.jsonl": list(entities.values()), "relationships.jsonl": list(relations.values()), "documents.jsonl": documents, "conflicts.jsonl": conflicts}


def encoded_artifacts(data):
    result = {}
    for name in CORE_NAMES:
        value = data[name]
        if name.endswith(".jsonl"):
            value = sorted(value, key=lambda row: row["id"])
            rendered = "".join(canonical(row) + "\n" for row in value)
        else:
            rendered = canonical(value) + "\n"
        raw = rendered.encode("utf-8")
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise IndexErrorClosed(f"artifact too large: {name}")
        result[name] = raw
    return result


def validate_schema_contract(data):
    schema = json.loads(Path(__file__).with_name("schema.json").read_text(encoding="utf-8"))
    if schema.get("schemaVersion") != SCHEMA_VERSION or schema.get("indexerVersion") != INDEXER_VERSION or set(schema.get("entityTypes", [])) != ENTITY_TYPES or set(schema.get("relationshipTypes", [])) != REL_TYPES:
        raise IndexErrorClosed("schema contract/version mismatch")
    for name, required in (("sources.jsonl", "sourceRecordRequired"), ("entities.jsonl", "entityRequired"), ("relationships.jsonl", "relationshipRequired"), ("documents.jsonl", "documentUnitRequired"), ("conflicts.jsonl", "findingRequired")):
        required_keys = set(schema[required])
        if any(not required_keys.issubset(row) for row in data[name]):
            raise IndexErrorClosed(f"schema-required field missing: {name}")


def output_dir(root, output):
    expected = root.resolve() / "data" / "generated" / "kermit-index"
    resolved = output.resolve()
    if resolved != expected:
        raise IndexErrorClosed("output must be the isolated data/generated/kermit-index directory")
    return resolved


def report_text(data, stale=0, missing=0, errors=()):
    counts = Counter(row["type"] for row in data["entities.jsonl"])
    return "\n".join([f"Kermit L2 build report (indexer {INDEXER_VERSION}, schema {SCHEMA_VERSION})", f"Admitted sources: {len(data['sources.jsonl'])}", f"Document units: {len(data['documents.jsonl'])}", "Entity counts: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)), f"Relationships: {len(data['relationships.jsonl'])}", f"Findings: {len(data['conflicts.jsonl'])}", f"Stale: {stale}; missing: {missing}", f"Errors: {len(errors)}", "Rejected sources: 0 (no unlisted files are opened)", "Output: data/generated/kermit-index", "Core: " + ", ".join(CORE_NAMES), "Derived metadata only; no runtime state indexed."])


def build(root, manifest, output):
    data = build_data(root, manifest)
    validate_schema_contract(data)
    raw = encoded_artifacts(data)
    output = output_dir(root, output)
    output.mkdir(parents=True, exist_ok=True)
    for name, body in raw.items():
        temporary = output / (name + ".tmp")
        temporary.write_bytes(body)
        os.replace(temporary, output / name)
    (output / "build.json").write_text(canonical({"schemaVersion": SCHEMA_VERSION, "indexerVersion": INDEXER_VERSION, "sourceCount": len(data["sources.jsonl"]), "coreSha256": {name: digest(raw[name]) for name in CORE_NAMES}}) + "\n", encoding="utf-8")
    result = validate(root, manifest, output)
    (output / "report.txt").write_text(result + "\n", encoding="utf-8")
    return result


def validate(root, manifest, output):
    output = output_dir(root, output)
    expected = build_data(root, manifest)
    validate_schema_contract(expected)
    encoded = encoded_artifacts(expected)
    for name, body in encoded.items():
        path = output / name
        if not path.is_file():
            raise IndexErrorClosed(f"missing artifact: {name}")
        if path.stat().st_size > MAX_ARTIFACT_BYTES or path.read_bytes() != body:
            raise IndexErrorClosed(f"stale or malformed artifact: {name}")
    build_path = output / "build.json"
    if not build_path.is_file() or build_path.stat().st_size > 100_000:
        raise IndexErrorClosed("missing or oversized build metadata")
    build_meta = json.loads(build_path.read_text(encoding="utf-8"))
    if build_meta != {"schemaVersion": SCHEMA_VERSION, "indexerVersion": INDEXER_VERSION, "sourceCount": len(expected["sources.jsonl"]), "coreSha256": {name: digest(encoded[name]) for name in CORE_NAMES}}:
        raise IndexErrorClosed("stale or malformed build metadata")
    ids = [row["id"] for row in expected["entities.jsonl"]]
    if len(ids) != len(set(ids)) or any(row["type"] not in ENTITY_TYPES or row.get("schemaVersion") != SCHEMA_VERSION or not row.get("privacyClassification") or not row.get("provenance") for row in expected["entities.jsonl"]):
        raise IndexErrorClosed("invalid entity IDs/schema/provenance")
    known_sources = {row["id"]: row for row in expected["sources.jsonl"]}
    for name in ("entities.jsonl", "relationships.jsonl", "documents.jsonl", "conflicts.jsonl"):
        for row in expected[name]:
            if row.get("schemaVersion") != SCHEMA_VERSION or not row.get("provenance"):
                raise IndexErrorClosed(f"missing schema/provenance: {name}")
            for ref in row["provenance"]:
                source = known_sources.get(ref["sourceId"])
                if not source or ref["path"] != source["path"] or ref["fingerprint"] != source["sha256"]:
                    raise IndexErrorClosed(f"invalid source reference: {name}")
    for row in expected["relationships.jsonl"]:
        if row["type"] not in REL_TYPES or row["from"] not in ids or row["to"] not in ids:
            raise IndexErrorClosed("invalid relationship endpoint/type")
    return report_text(expected)
