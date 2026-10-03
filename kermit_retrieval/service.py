"""Deterministic evidence selection. No dashboard modules or runtime stores are imported."""

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from kermit_index.builder import CORE_NAMES, safe_path, IndexErrorClosed


CONTRACT_VERSION = 1
ROOT = Path(__file__).resolve().parent.parent
PILOTS = ("quote", "finance", "language-learning", "weather")
LIMITS = {"questionChars": 500, "items": 12, "documents": 4, "sourceExcerpts": 2,
          "excerptLines": 24, "excerptBytes": 1600, "evidenceBytes": 12000, "packBytes": 30000,
          "approxTokens": 3000, "relationshipDepth": 2, "relationships": 24,
          "artifactBytes": 20_000_000}
STOP = frozenset("a an and are as at be by can do does for from how i in is it me my of on or the this to use was what when where which who why with you your".split())
TOPIC = {"quote": ("quote", "quotable", "dummyjson", "randomquotes"),
         "finance": ("finance", "budget", "receipt", "transaction", "spend", "bank"),
         "language-learning": ("language", "learning", "stanza", "gemini", "anki", "audio", "generation", "reference"),
         "weather": ("weather", "forecast", "temperature", "open-meteo", "celsius"),
         "cleaning": ("cleaning", "cleaningstore", "chore", "apartment", "cleaning_actions"),
         "reading": ("reading", "readingstore", "book", "pages", "library"),
         "todo": ("todo", "todostore", "to-do", "subtask", "shopping"),
         "dashboard": ("dashboard", "widget", "widgets", "loader", "visibility", "order", "layout"),
         "settings": ("settings", "setting", "localstorage", "preference", "mirror"),
         "central-api": ("server.py", "central", "static", "security", "origin", "referer", "host", "port", "process", "runtime", "protected", "paths", "workout", "network", "kermit"),
         "habits-app": ("habits app", "habits.sqlite", "canonical habits", "habit sync", "supplement", "reminder", "regimen", "notification"),
         "habits-summary": ("habits summary", "legacy habits", "public/data/habits.json", "generated habits", "sobriety"),
         "habits-timeline": ("habits timeline", "habit-data.json", "habit-data.js", "loop habit", "habit upload", "habit csv"),
         "self-care": ("self-care", "self care", "selfcare", "timeline activity"),
         "weight-steps": ("weight", "weight-cut", "scale", "steps", "step", "manual", "automatic", "step history", "latest.json", "health connect", "ble"),
         "diet": ("diet", "meal", "calorie", "estimated calories", "diet.json", "suggestion"),
         "sleep": ("sleep", "sleep page", "sleep analysis", "night", "ring", "watch", "connect", "incomplete", "health connect sleep", "ring sleep"),
         "mental-health": ("mental health", "assessment", "questionnaire", "retest", "check-in", "checkin", "phq", "gad", "mental-health.sqlite"),
         "sensors": ("sensor", "temperature", "humidity", "room", "readings.jsonl", "sensor/latest.json", "sensor history"),
         "ble-collector": ("ble", "collector", "advertisement", "scan_ble", "scanner", "reconnect", "scale" ),
         "live-workout-strength": ("live workout", "workout", "training runtime", "strength", "strength set", "checkpoint", "virtual walk", "active session"),
         "heart-rate-history": ("heart-rate history", "heart rate history", "hr history", "bpm history", "smartwatch", "ring fallback", "watch reference", "heart_rate_telemetry"),
         "ring": ("colmi", "smart ring", "ring collector", "ring sync", "ring history", "ring phone", "ring wear"),
         "process-lifecycle": ("process lifecycle", "process", "start-dev", "start-dashboard", "start-all", "dev-service", "restart", "restarts", "port 8766", "port 8765", "vite process")}
# Reviewed query terms and reviewed L1 heading families. These are ranking hints,
# not permission to read another source or infer a fact absent from the index.
SECTION_INTENTS = {
    "jobs_recovery": ({"job", "worker", "queue", "retry", "retrie", "restart", "recovery", "recover",
                       "interruption", "interrupted", "resume", "cancellation", "cancel", "attempt", "backoff"},
                      ("job", "recovery", "worker", "queue")),
    "integrations_providers": ({"integration", "provider", "external", "dependency", "depend", "api"},
                               ("integration", "dependenc", "provider", "external")),
    "storage_ownership": ({"canonical", "store", "storage", "ownership", "persistence", "database", "sqlite"},
                          ("persistence", "source of truth", "storage", "ownership")),
    "metrics_calculations": ({"metric", "calculation", "calculate", "compute", "computed", "formula", "threshold", "temperature", "target", "average", "overdue", "progress"},
                             ("metric", "calculation")),
    "failure_degraded": ({"fail", "failure", "degraded", "offline", "unavailable"},
                         ("failure", "degraded", "recovery")),
    "data_flow": ({"flow", "transformation", "transform", "pipeline"}, ("data flow", "transformation")),
    "frontend": ({"frontend", "ui", "display", "render"}, ("frontend",)),
    "backend_api": ({"backend", "route", "endpoint", "api"}, ("backend", "api")),
}
CONFLICT_TERMS = {
    "Q-01": ("provider", "fallback", "fail", "test"),
    "W-01": ("forecast", "loading", "fail", "test"),
    "W-02": ("temperature", "null", "zero", "scale", "display"),
    "F-01": ("csv", "import", "archive", "documentation", "disagree"),
    "F-02": ("date", "utc", "timezone", "semantics"),
    "F-03": ("freshness", "threshold", "stale"),
    "F-04": ("category", "receipt", "split", "calculation", "disagree"),
    "L-01": ("gemini", "schema", "documentation", "disagree"),
}
DESIGN = "docs/kermit/"
PACK = "docs/kermit/knowledge/subsystems/"
GAPS = "docs/kermit/knowledge/GAPS_AND_CONFLICTS.md"


class RetrievalError(ValueError):
    """The snapshot or request cannot safely be used."""


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _tokens(value):
    folded = unicodedata.normalize("NFKC", value).casefold()
    words = re.findall(r"[^\W_]+", folded, re.UNICODE)
    return tuple((t[:-1] if t.endswith("s") and not t.endswith(("ss", "us", "ics")) and len(t) > 4 else t) for t in words if t not in STOP and len(t) > 1)


def _words(value):
    return set(_tokens(value))


def _normalize_question(value):
    if not isinstance(value, str) or not value.strip() or len(value) > LIMITS["questionChars"] or "\x00" in value:
        raise RetrievalError("question must be nonempty UTF-8 text within the character limit")
    try:
        value.encode("utf-8", "strict")
    except UnicodeError as exc:
        raise RetrievalError("question is not valid UTF-8 text") from exc
    return " ".join(unicodedata.normalize("NFKC", value).split())


class Snapshot:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        folder = self.root / "data/generated/kermit-index"
        try:
            for candidate in (self.root / "data", self.root / "data/generated", folder, folder / "build.json", self.root / "kermit_index", self.root / "kermit_index/admission.json"):
                if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                    raise RetrievalError("unsafe index or admission path")
                if not candidate.resolve().is_relative_to(self.root):
                    raise RetrievalError("index path escaped repository root")
            build = json.loads((folder / "build.json").read_text(encoding="utf-8"))
            if build.get("schemaVersion") != 1 or build.get("indexerVersion") != "1.0.0":
                raise RetrievalError("unsupported index revision")
            raw = {}
            for name in CORE_NAMES:
                path = folder / name
                if path.is_symlink() or getattr(path, "is_junction", lambda: False)() or path.stat().st_size > LIMITS["artifactBytes"]:
                    raise RetrievalError("unsafe index artifact")
                raw[name] = path.read_bytes()
                if _hash(raw[name]) != build["coreSha256"][name]:
                    raise RetrievalError("index artifact fingerprint mismatch")
            self.build_fingerprint = _hash((folder / "build.json").read_bytes())
            self.manifest = json.loads(raw["manifest.json"])
            source_rows = self._rows(raw["sources.jsonl"])
            entity_rows = self._rows(raw["entities.jsonl"])
            self.sources = {r["id"]: r for r in source_rows}
            self.entities = {r["id"]: r for r in entity_rows}
            self.relationships = self._rows(raw["relationships.jsonl"])
            self.documents = self._rows(raw["documents.jsonl"])
            self.conflicts = self._rows(raw["conflicts.jsonl"])
            for rows in (source_rows, entity_rows, self.relationships, self.documents, self.conflicts):
                if len({r["id"] for r in rows}) != len(rows) or any(r.get("schemaVersion") != 1 for r in rows):
                    raise RetrievalError("invalid or duplicate index records")
            admission = json.loads((self.root / "kermit_index/admission.json").read_text(encoding="utf-8"))
            expected = {e["path"]: {"path": e["path"], "subsystem": e["subsystem"], **admission["defaults"][e["group"]]} for e in admission["entries"]}
            actual = {r["path"]: {k: r[k] for k in ("path", "subsystem", "sourceClass", "expectedRole", "privacyClassification", "parserMode", "contentMode", "maxBytes")} for r in self.sources.values()}
            if admission["schemaVersion"] != 1 or expected != actual or self.manifest["sources"] != [actual[p] for p in sorted(actual)]:
                raise RetrievalError("index admission does not match positive policy")
            if build["sourceCount"] != len(self.sources) or len(self.sources) != len(expected):
                raise RetrievalError("invalid source count")
            for row in self.documents:
                ref = row["provenance"][0]
                source = self.sources[ref["sourceId"]]
                if (row["sourceFingerprint"] != source["sha256"] or ref["path"] != source["path"]
                        or source["contentMode"] != "sections" or row["parentDocument"] not in self.entities
                        or not isinstance(row["content"], str)):
                    raise RetrievalError("invalid document provenance")
            for row in list(self.entities.values()) + self.relationships + self.conflicts:
                for ref in row["provenance"]:
                    source = self.sources[ref["sourceId"]]
                    if ref["path"] != source["path"] or ref["fingerprint"] != source["sha256"]:
                        raise RetrievalError("invalid index provenance")
            for finding in self.conflicts:
                for side_name in ("sideA", "sideB"):
                    for ref in finding[side_name]["expectedSourceRefs"]:
                        source = self.sources.get(ref["sourceId"])
                        if (not source or ref["path"] != source["path"] or
                                ref["sourceSha256"] != source["sha256"]):
                            raise RetrievalError("invalid finding side provenance")
            if any(r["from"] not in self.entities or r["to"] not in self.entities for r in self.relationships):
                raise RetrievalError("invalid relationship endpoint")
        except (OSError, KeyError, TypeError, json.JSONDecodeError, UnicodeError, IndexErrorClosed) as exc:
            raise RetrievalError("invalid or unavailable Phase 3 snapshot") from exc
        self.freshness = {}
        document_text = {}
        for sid, source in self.sources.items():
            group = "documentation" if source["contentMode"] == "sections" else "test" if source["sourceClass"] == "project_test" else "source"
            try:
                path = safe_path(self.root, source["path"], group, source["maxBytes"])
                with path.open("rb") as stream:
                    data = stream.read(source["maxBytes"] + 1)
                status = "current" if len(data) <= source["maxBytes"] and _hash(data) == source["sha256"] else "stale"
                if status == "current" and source["contentMode"] == "sections":
                    if b"\x00" in data:
                        status = "missing_or_unsafe"
                    else:
                        document_text[sid] = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            except (OSError, IndexErrorClosed, UnicodeError):
                status = "missing_or_unsafe"
            self.freshness[sid] = status
        # A self-consistent artifact checksum is not sufficient if a derived section
        # was edited without a matching admitted source edit.
        for row in self.documents:
            source = self.sources[row["provenance"][0]["sourceId"]]
            sid = source["id"]
            if self.freshness[sid] != "current":
                continue
            if row["content"] not in document_text[sid]:
                raise RetrievalError("document unit no longer matches admitted source")

    @staticmethod
    def _rows(raw):
        return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]

    def read_symbol(self, entity):
        """Only an indexed source symbol may request a small L3 excerpt."""
        if (not isinstance(entity, dict) or self.entities.get(entity.get("id")) != entity
                or entity.get("type") != "symbol" or not isinstance(entity.get("lineStart"), int)):
            raise RetrievalError("source excerpt requires an indexed symbol span")
        ref = entity["sourceReferences"][0]
        source = self.sources.get(ref["sourceId"])
        if (not source or source["sourceClass"] != "project_source" or source["contentMode"] != "metadata_only"
                or self.freshness[source["id"]] != "current" or ref["fingerprint"] != source["sha256"]
                or ref["path"] != source["path"]):
            raise RetrievalError("source excerpt is not admitted and current")
        try:
            path = safe_path(self.root, source["path"], "source", source["maxBytes"])
            raw = path.read_bytes()
            if b"\x00" in raw or _hash(raw) != source["sha256"]:
                raise RetrievalError("source changed while reading")
            lines = raw.decode("utf-8").splitlines()
        except (OSError, UnicodeError, IndexErrorClosed) as exc:
            raise RetrievalError("source excerpt read rejected") from exc
        start = entity["lineStart"]
        end = min(entity.get("lineEnd", start), len(lines))
        if start < 1 or end < start:
            raise RetrievalError("invalid indexed source span")
        end = min(end, start + LIMITS["excerptLines"] - 1)
        selected = []
        used = 0
        for line in lines[start - 1:end]:
            encoded = (line + "\n").encode("utf-8")
            if used + len(encoded) > LIMITS["excerptBytes"]:
                break
            selected.append(line)
            used += len(encoded)
        if not selected:
            raise RetrievalError("indexed line exceeds excerpt limit")
        return "\n".join(selected), start, start + len(selected) - 1, start + len(selected) - 1 < entity.get("lineEnd", start)

    def read_reviewed_ref(self, ref):
        """Read only a fixed, indexed finding span from a current admitted source."""
        source = self.sources.get(ref["sourceId"])
        if (not source or source["path"] != ref["path"] or source["sha256"] != ref["sourceSha256"]
                or self.freshness[source["id"]] != "current"):
            raise RetrievalError("finding side is not admitted and current")
        group = ("documentation" if source["contentMode"] == "sections" else
                 "test" if source["sourceClass"] == "project_test" else "source")
        if source["sourceClass"] not in ("reviewed_documentation", "project_source", "project_test"):
            raise RetrievalError("finding side source class is unsupported")
        try:
            path = safe_path(self.root, source["path"], group, source["maxBytes"])
            raw = path.read_bytes()
            if _hash(raw) != source["sha256"] or b"\x00" in raw:
                raise RetrievalError("finding side source changed")
            lines = raw.decode("utf-8").splitlines()
        except (OSError, UnicodeError, IndexErrorClosed) as exc:
            raise RetrievalError("finding side read rejected") from exc
        first, last = ref["lineStart"], ref["lineEnd"]
        if (not isinstance(first, int) or not isinstance(last, int) or first < 1
                or last < first or last - first >= LIMITS["excerptLines"] or last > len(lines)):
            raise RetrievalError("invalid reviewed finding span")
        excerpt = "\n".join(lines[first - 1:last])
        if ref["anchor"] not in excerpt or len(excerpt.encode("utf-8")) > LIMITS["excerptBytes"]:
            raise RetrievalError("finding side anchor or byte limit failed")
        return excerpt


def _context(context, entities):
    if context is None:
        return {}
    if not isinstance(context, dict) or set(context) - {"subsystemId", "pageId", "widgetId", "route", "entityType"}:
        raise RetrievalError("unknown context field")
    resolved = {}
    kinds = {"subsystemId": "subsystem", "pageId": "page", "widgetId": "widget"}
    for field, kind in kinds.items():
        if field in context:
            value = context[field]
            item = entities.get(value) if isinstance(value, str) else None
            if not item or item["type"] != kind:
                raise RetrievalError("unknown context identifier")
            resolved[field] = value
    if "route" in context:
        route = context["route"]
        if not isinstance(route, str) or not any(e.get("route") == route for e in entities.values() if e["type"] == "api_operation"):
            raise RetrievalError("unknown route context")
        resolved["route"] = route
    if "entityType" in context:
        value = context["entityType"]
        if not isinstance(value, str) or value not in {e["type"] for e in entities.values()}:
            raise RetrievalError("unknown entity type")
        resolved["entityType"] = value
    return resolved


def _claim(question):
    terms = set(re.findall(r"[^\W_]+", question.casefold(), re.UNICODE))
    if terms & {"proposed", "proposal", "roadmap", "kermit", "planned"}:
        return "design"
    if terms & {"function", "handler", "route", "code", "implementation", "symbol"}:
        return "implementation"
    if terms & {"ownership", "architecture", "boundary", "canonical", "store", "source", "truth"}:
        return "ownership"
    if terms & {"calculated", "calculate", "calculation", "compute", "computed", "metric", "threshold", "formula", "deduplicated"}:
        return "calculation"
    if terms & {"do", "does", "happens", "used", "uses", "work", "works", "backend", "provider", "fails", "recover"}:
        return "behavior"
    return "unknown"


def _overlap(query, text):
    return len(query & _words(text))


def _section_intents(terms):
    return tuple(name for name, (query_terms, _) in SECTION_INTENTS.items() if terms & query_terms)


def _heading_intents(heading, active):
    lowered = heading.casefold()
    return tuple(name for name in active if any(marker in lowered for marker in SECTION_INTENTS[name][1]))


def retrieve(request, *, root=ROOT):
    if not isinstance(request, dict) or set(request) - {"contractVersion", "question", "optionalContext"} or request.get("contractVersion") != CONTRACT_VERSION:
        raise RetrievalError("unsupported query contract")
    question = _normalize_question(request.get("question"))
    tokens = _tokens(question)
    terms = set(tokens)
    section_intents = _section_intents(terms)
    snapshot = Snapshot(root)
    context = _context(request.get("optionalContext"), snapshot.entities)
    claim = _claim(question)
    explicit_findings = {c["id"].split(":")[1] for c in snapshot.conflicts if c["id"].split(":")[1].casefold() in question.casefold()}
    context_subsystems = {snapshot.entities[v].get("owningSubsystem") for k, v in context.items() if k.endswith("Id")}
    # The four historical pilot benchmarks retain their comparison scope. New
    # subsystem IDs participate only when their reviewed pack is indexed.
    scope = PILOTS if "pilot" in terms else tuple(s for s in TOPIC if f"subsystem:{s}" in snapshot.entities)
    sub_scores = {}
    for sub in scope:
        aliases = set(TOPIC[sub]) | set(_tokens(sub.replace("-", " ")))
        score = 8 * len(terms & aliases) + (5 if sub in context_subsystems else 0)
        if sub == "ble-collector" and {"ble", "reconnect"} <= terms:
            score += 9
        if sub == "ble-collector" and "ble collector" in question.casefold():
            score += 9
        if sub == "mental-health" and re.search(r"\bcheck[- ]?in\b", question, re.I):
            score += 17
        if sub == "sensors" and {"room", "temperature"} <= terms:
            score += 9
        if sub == "process-lifecycle" and ("start-dev" in question.casefold() or {"process", "restart"} <= terms or {"process", "restarts"} <= terms):
            score += 40
        if sub == "live-workout-strength" and "training runtime" in question.casefold():
            score += 24
        if sub in terms:
            score += 6
        score += 9 * sum(c["subsystem"] == sub for c in snapshot.conflicts if c["id"].split(":")[1] in explicit_findings)
        sub_scores[sub] = score
    candidates = [s for s in scope if sub_scores[s] > 0]
    if not candidates:
        candidates = list(PILOTS)
    candidates.sort(key=lambda s: (-sub_scores[s], s))
    # A broad question is allowed to compare pilots; a focused question stays focused.
    cross = not candidates or (len(candidates) > 1 and max(sub_scores.values()) - min(sub_scores[s] for s in candidates) <= 8)
    selected_subs = candidates[:4] if cross else candidates[:1]
    if not selected_subs:
        selected_subs = list(PILOTS)
    broad_findings = not any(score > 0 for score in sub_scores.values()) and bool(terms & {"finding", "conflict", "gap"})
    planned_findings = [f for f in snapshot.conflicts if f["subsystem"] in selected_subs and
                        (f["id"].split(":")[1] in explicit_findings or broad_findings or
                         len(terms & set(CONFLICT_TERMS[f["id"].split(":")[1]])) >= 2)]
    planned_findings.sort(key=lambda f: (f["id"].split(":")[1] not in explicit_findings, f["id"]))
    lookup_terms = terms - {"quote", "finance", "weather", "language", "learning", "cleaning", "reading", "todo"}
    if not lookup_terms:
        lookup_terms = terms
    stale = sorted(s["id"] for s in snapshot.sources.values() if snapshot.freshness[s["id"]] != "current")
    uncertainty = []
    if stale:
        uncertainty.append("Changed, missing, or unsafe admitted sources were withheld; rebuild Phase 3 separately before treating them as current.")
    if claim == "unknown":
        uncertainty.append("Claim type is unclear; evidence retains mixed authority and status.")
    scored_entities = []
    for entity in snapshot.entities.values():
        sub = entity.get("owningSubsystem", "shared")
        if sub not in selected_subs and sub != "shared":
            continue
        if entity["type"] in ("document", "subsystem", "conflict"):
            continue
        if any(snapshot.freshness.get(ref["sourceId"]) != "current" for ref in entity["sourceReferences"]):
            continue
        name = entity["displayName"]
        ids = entity["id"].replace("_", " ").replace("-", " ")
        overlap = _overlap(lookup_terms, name)
        exact = 1 if entity["id"].casefold() in question.casefold() or name.casefold() in question.casefold() and len(name) > 5 else 0
        alias = _overlap(terms, " ".join(entity.get("aliases", [])))
        route = _overlap(terms, entity.get("route", ""))
        components = {"name": 5 * overlap, "exact": 10 * exact, "alias": 4 * alias,
                      "route": 3 * route, "subsystem": 2 if sub in candidates else 0,
                      "contextType": 3 if context.get("entityType") == entity["type"] else 0,
                      "ownership": 0}
        if claim == "ownership" and (entity["type"] == "store" and ("store" in terms or "storage" in terms or "canonical" in terms) or entity.get("storageRole") == "canonical" and "canonical" in terms):
            components["ownership"] = 9
        score = sum(components.values())
        if score > 2 and (overlap or exact or alias or route or score >= 9 and claim == "ownership"):
            scored_entities.append((score, entity, components))
    scored_entities.sort(key=lambda item: (-item[0], item[1]["id"]))
    # Bounded graph expansion follows indexed relationships only, with no inferred edges.
    adjacency = defaultdict(list)
    for rel in snapshot.relationships:
        adjacency[rel["from"]].append(rel)
        adjacency[rel["to"]].append(rel)
    queue = deque((entity["id"], 0) for _, entity, _ in scored_entities[:3])
    visited = {id for id, _ in queue}
    traversed = []
    while queue and len(traversed) < LIMITS["relationships"]:
        eid, depth = queue.popleft()
        if depth >= LIMITS["relationshipDepth"]:
            continue
        def edge_key(rel):
            target = rel["to"] if rel["from"] == eid else rel["from"]
            useful_type = rel["type"] in {"renders", "handles", "exposes", "imports", "reads", "writes", "processes"}
            return (-_overlap(terms, snapshot.entities[target]["displayName"]), -int(useful_type), rel["id"])
        for rel in sorted(adjacency[eid], key=edge_key)[:8]:
            target = rel["to"] if rel["from"] == eid else rel["from"]
            other = snapshot.entities[target]
            if other.get("owningSubsystem", "shared") not in selected_subs + ["shared"] or target in visited:
                continue
            if any(snapshot.freshness.get(ref["sourceId"]) != "current" for ref in other["sourceReferences"]):
                continue
            if any(snapshot.freshness.get(ref["sourceId"]) != "current" for ref in rel["provenance"]):
                continue
            visited.add(target)
            traversed.append({"relationshipId": rel["id"], "type": rel["type"], "from": eid, "to": target,
                              "depth": depth + 1, "reason": "indexed edge ranked by target name and relation type",
                              "targetNameOverlap": _overlap(terms, other["displayName"])})
            if len(traversed) >= LIMITS["relationships"]:
                break
            queue.append((target, depth + 1))
    doc_candidates = []
    for doc in snapshot.documents:
        source = snapshot.sources[doc["provenance"][0]["sourceId"]]
        path = source["path"]
        if snapshot.freshness[source["id"]] != "current" or doc["subsystem"] not in selected_subs + ["shared"]:
            continue
        if path.startswith(DESIGN) and not path.startswith(PACK) and path != GAPS and claim != "design":
            continue
        if path == GAPS and not explicit_findings:
            continue
        if path == GAPS and not any(code in doc["heading"] for code in explicit_findings):
            continue
        if path.startswith(PACK) and doc["subsystem"] in {"dashboard", "settings", "central-api"} and (
                doc["heading"].endswith("reviewed L1 pack") or doc["heading"] == "Checked implementation references"):
            continue
        heading = _overlap(terms, doc["heading"])
        body = _overlap(terms, doc["content"])
        components = {"heading": 7 * heading, "content": min(12, 2 * body), "sourceRole": 0,
                      "sectionIntent": 0, "subsystem": 3 if doc["subsystem"] in candidates else 0, "finding": 0}
        if path.startswith(PACK):
            components["sourceRole"] = 12 if claim in ("behavior", "unknown", "ownership") else 8
            if doc["subsystem"] in selected_subs and not cross:
                components["sourceRole"] += 12
        elif path == "PROJECT_MAP.md" and claim == "ownership":
            components["sourceRole"] = 8
        elif path.startswith(DESIGN) and claim == "design":
            components["sourceRole"] = 8
        if path == GAPS:
            components["finding"] = 25
        preferred = {"ownership": ("persistence", "purpose", "boundaries", "identity"),
                     "calculation": ("metrics", "calculations"),
                     "implementation": ("backend", "api", "frontend", "tests"),
                     "behavior": ("purpose", "frontend", "backend", "flow", "integrations")}
        if any(word in doc["heading"].casefold() for word in preferred.get(claim, ())):
            components["sectionIntent"] = 8
        matched_intents = _heading_intents(doc["heading"], section_intents)
        if matched_intents:
            components["sectionIntent"] += 28
        score = sum(components.values())
        if score >= 10 and (heading or body or matched_intents or path == GAPS):
            doc_candidates.append((score, doc, components))
    doc_candidates.sort(key=lambda item: (-item[0], item[1]["id"]))
    if explicit_findings:
        doc_candidates.sort(key=lambda item: 0 if item[1]["provenance"][0]["path"] == GAPS
                            and item[1]["heading"] in explicit_findings else 1)
    balanced_doc_ids = set()
    if cross:
        if section_intents:
            doc_candidates = [pair for pair in doc_candidates if _heading_intents(pair[1]["heading"], section_intents)
                              or pair[1]["provenance"][0]["path"] == GAPS]
        first = []
        used = set()
        covered_subs = set()
        for choice in doc_candidates:
            sub = choice[1]["subsystem"]
            if sub not in selected_subs or sub in covered_subs or not choice[1]["provenance"][0]["path"].startswith(PACK):
                continue
            first.append(choice)
            used.add(choice[1]["id"])
            balanced_doc_ids.add(choice[1]["id"])
            covered_subs.add(sub)
        doc_candidates = first + [pair for pair in doc_candidates if pair[1]["id"] not in used]
    evidence = []
    omitted = defaultdict(int)
    bytes_used = 0
    def add(item, kind):
        nonlocal bytes_used
        if len(evidence) >= LIMITS["items"] or sum(e["layer"] == "L1" for e in evidence) >= LIMITS["documents"] and kind == "L1" or sum(e["layer"] == "L3" for e in evidence) >= LIMITS["sourceExcerpts"] and kind == "L3":
            omitted["item_or_layer_limit"] += 1
            return False
        item["evidenceId"] = f"E{len(evidence) + 1}"
        size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if bytes_used + size > LIMITS["evidenceBytes"]:
            omitted["byte_limit"] += 1
            return False
        bytes_used += size
        evidence.append(item)
        return True
    reviewed_doc_refs = [ref for finding in planned_findings for side in ("sideA", "sideB")
                         for ref in finding[side]["expectedSourceRefs"]
                         if snapshot.sources[ref["sourceId"]]["contentMode"] == "sections"]
    ordinary_doc_limit = LIMITS["documents"] - min(len(reviewed_doc_refs), 2)
    for score, doc, components in doc_candidates:
        source = snapshot.sources[doc["provenance"][0]["sourceId"]]
        content = doc["content"]
        clipped = content[:900]
        signals = (["section_intent_match"] if _heading_intents(doc["heading"], section_intents) else [])
        if sub_scores.get(doc["subsystem"], 0) > 0:
            signals.append("subsystem_match")
        if components["heading"] or components["content"] >= 4:
            signals.append("direct_match")
        if source["path"] == GAPS:
            signals.append("finding_match")
        add({"layer": "L1", "sourceId": source["id"], "entityIds": [doc["parentDocument"]], "sourceClass": source["sourceClass"],
             "authorityRole": "design" if source["path"].startswith(DESIGN) and not source["path"].startswith(PACK) else "reviewed_explanation" if source["path"].startswith(PACK) else "documented_inventory",
             "factStatus": doc["sourceStatus"], "subsystem": doc["subsystem"], "path": source["path"],
             "locator": {"heading": doc["heading"], "lineStart": doc["lineStart"], "lineEnd": doc["lineEnd"]},
             "excerpt": clipped, "sourceSha256": source["sha256"], "indexSchemaVersion": 1,
             "freshness": "current", "storageRole": None, "privacyClassification": source["privacyClassification"],
             "reasonSelected": ("cross-system section-intent first slot" if section_intents else "cross-system lexical first slot") if doc["id"] in balanced_doc_ids else
                               "L1 section-intent match" if "section_intent_match" in signals else "L1 heading/content lexical match",
             "relevanceSignals": signals, "score": score, "scoreComponents": components,
             "conflictRefs": [], "truncated": doc["truncated"] or len(clipped) < len(content)}, "L1")
        if sum(e["layer"] == "L1" for e in evidence) >= ordinary_doc_limit:
            break
    for finding in planned_findings:
        for side_name in ("sideA", "sideB"):
            for ref in finding[side_name]["expectedSourceRefs"]:
                source = snapshot.sources[ref["sourceId"]]
                if source["contentMode"] != "sections" or snapshot.freshness[source["id"]] != "current":
                    continue
                try:
                    excerpt = snapshot.read_reviewed_ref(ref)
                except RetrievalError:
                    continue
                add({"layer": "L1", "sourceId": source["id"], "entityIds": [], "sourceClass": source["sourceClass"],
                     "authorityRole": "documented_inventory", "factStatus": "current", "subsystem": finding["subsystem"],
                     "path": source["path"], "locator": {"lineStart": ref["lineStart"], "lineEnd": ref["lineEnd"]},
                     "excerpt": excerpt, "sourceSha256": source["sha256"], "indexSchemaVersion": 1,
                     "freshness": "current", "storageRole": None, "privacyClassification": source["privacyClassification"],
                     "reasonSelected": "reviewed finding side", "relevanceSignals": ["finding_match"],
                     "score": 100, "scoreComponents": {"finding": 100},
                     "conflictRefs": [finding["id"]], "truncated": False}, "L1")
    for finding in planned_findings:
        for side_name in ("sideA", "sideB"):
            for ref in finding[side_name]["expectedSourceRefs"]:
                source = snapshot.sources[ref["sourceId"]]
                if source["contentMode"] == "sections" or snapshot.freshness[source["id"]] != "current":
                    continue
                try:
                    excerpt = snapshot.read_reviewed_ref(ref)
                except RetrievalError:
                    continue
                add({"layer": "L3", "sourceId": source["id"], "entityIds": [], "sourceClass": source["sourceClass"],
                     "authorityRole": "current_test" if source["sourceClass"] == "project_test" else "current_source",
                     "factStatus": "indexed_current_span", "subsystem": finding["subsystem"],
                     "path": source["path"], "locator": {"lineStart": ref["lineStart"], "lineEnd": ref["lineEnd"]},
                     "excerpt": excerpt, "sourceSha256": source["sha256"], "indexSchemaVersion": 1,
                     "freshness": "current", "storageRole": None, "privacyClassification": source["privacyClassification"],
                     "reasonSelected": "reviewed finding side", "relevanceSignals": ["finding_match"],
                     "score": 100, "scoreComponents": {"finding": 100},
                     "conflictRefs": [finding["id"]], "truncated": False}, "L3")
    # Reserve room for exact source evidence before broader entity metadata.
    if claim in ("implementation", "calculation"):
        for score, entity, _ in scored_entities:
            if entity["type"] != "symbol" or score < 10:
                continue
            try:
                excerpt, first, last, truncated = snapshot.read_symbol(entity)
            except RetrievalError:
                continue
            ref = entity["sourceReferences"][0]
            source = snapshot.sources[ref["sourceId"]]
            add({"layer": "L3", "sourceId": source["id"], "entityIds": [entity["id"]], "sourceClass": source["sourceClass"],
                 "authorityRole": "current_source", "factStatus": "indexed_current_symbol", "subsystem": entity.get("owningSubsystem"),
                 "path": source["path"], "locator": {"symbol": entity["displayName"], "lineStart": first, "lineEnd": last},
                 "excerpt": excerpt, "sourceSha256": source["sha256"], "indexSchemaVersion": 1, "freshness": "current",
             "storageRole": None, "privacyClassification": source["privacyClassification"], "reasonSelected": "L3 indexed symbol for implementation claim",
                 "relevanceSignals": ["subsystem_match"] if sub_scores.get(entity.get("owningSubsystem"), 0) > 0 else ["direct_match"],
                 "score": score, "scoreComponents": {"entityMatch": score}, "conflictRefs": [], "truncated": truncated}, "L3")
            if sum(e["layer"] == "L3" for e in evidence) >= LIMITS["sourceExcerpts"]:
                break
    for score, entity, components in scored_entities[:12]:
        ref = entity["sourceReferences"][0]
        source = snapshot.sources[ref["sourceId"]]
        if entity["type"] == "symbol" and claim not in ("implementation", "calculation") and score < 10:
            continue
        signals = []
        if sub_scores.get(entity.get("owningSubsystem"), 0) > 0:
            signals.append("subsystem_match")
        if entity["type"] == "integration" and "integrations_providers" in section_intents or entity["type"] == "store" and "storage_ownership" in section_intents:
            signals.append("section_intent_match")
        if components["name"] or components["exact"] or components["alias"]:
            signals.append("direct_match")
        add({"layer": "L2", "sourceId": source["id"], "entityIds": [entity["id"]], "sourceClass": source["sourceClass"],
             "authorityRole": "implementation_metadata" if source["sourceClass"] == "project_source" else "documented_metadata",
             "factStatus": entity.get("implementationStatus", entity.get("status", "indexed")), "subsystem": entity.get("owningSubsystem", "shared"),
             "path": source["path"], "locator": {"symbol": entity["displayName"] if entity["type"] == "symbol" else None,
             "route": entity.get("route"), "entityId": entity["id"], "lineStart": entity.get("lineStart"), "lineEnd": entity.get("lineEnd"), "sourceLocator": ref["locator"]},
             "metadata": {"type": entity["type"], "name": entity["displayName"], "storageRole": entity.get("storageRole")},
             "sourceSha256": source["sha256"], "indexSchemaVersion": 1, "freshness": "current",
             "storageRole": entity.get("storageRole"), "privacyClassification": source["privacyClassification"],
             "reasonSelected": "L2 entity lexical match", "score": score, "scoreComponents": components,
             "relevanceSignals": signals,
             "relationshipRefs": [r for r in traversed if entity["id"] in (r["from"], r["to"])][:4],
             "conflictRefs": [], "truncated": False}, "L2")
        if len(evidence) >= LIMITS["items"]:
            break
    conflicts = []
    for finding in snapshot.conflicts:
        code = finding["id"].split(":")[1]
        if snapshot.freshness[finding["provenance"][0]["sourceId"]] != "current":
            continue
        if finding["subsystem"] not in selected_subs:
            continue
        overlap = len(terms & set(CONFLICT_TERMS[code]))
        if broad_findings or code in explicit_findings or overlap >= 2 and any(e["subsystem"] == finding["subsystem"] for e in evidence):
            finding = dict(finding)
            finding["registerEvidenceId"] = next((item["evidenceId"] for item in evidence
                if item["path"] == GAPS and item["locator"].get("heading") == code), None)
            for side_name in ("sideA", "sideB"):
                side = dict(finding[side_name])
                side["requiredRefCount"] = len(side["expectedSourceRefs"])
                side["selectedEvidenceIds"] = [item["evidenceId"] for ref in side["expectedSourceRefs"]
                    for item in evidence if item["sourceId"] == ref["sourceId"]
                    and item["sourceSha256"] == ref["sourceSha256"]
                    and item["locator"].get("lineStart") == ref["lineStart"]
                    and item["locator"].get("lineEnd") == ref["lineEnd"]
                    and ref["anchor"] in item.get("excerpt", "")]
                if code not in explicit_findings:
                    side["expectedSourceRefs"] = [ref for ref in side["expectedSourceRefs"]
                        if any(item["sourceId"] == ref["sourceId"]
                               and item["locator"].get("lineStart") == ref["lineStart"]
                               and item["locator"].get("lineEnd") == ref["lineEnd"] for item in evidence)]
                finding[side_name] = side
            has_a = bool(finding["sideA"]["requiredRefCount"]) and len(finding["sideA"]["selectedEvidenceIds"]) == finding["sideA"]["requiredRefCount"]
            has_b = bool(finding["sideB"]["requiredRefCount"]) and len(finding["sideB"]["selectedEvidenceIds"]) == finding["sideB"]["requiredRefCount"]
            if finding["category"] in ("TEST_COVERAGE_GAP", "UNKNOWN_BEHAVIOR"):
                finding["status"] = "not_a_two_sided_conflict"
            elif has_a and has_b:
                finding["status"] = ("independently_cited" if finding["category"] in
                                     ("FACTUAL_CONFLICT", "DOCUMENTATION_DRIFT") else "not_a_two_sided_conflict")
            else:
                finding["status"] = "register_summary_only" if finding["registerEvidenceId"] else "insufficient_primary_evidence"
            conflicts.append(finding)
            for item in evidence:
                words = _words(item.get("excerpt", "") + " " + item.get("metadata", {}).get("name", "") + " " + str(item["locator"].get("heading") or ""))
                if item["subsystem"] == finding["subsystem"] and (len(words & set(CONFLICT_TERMS[code])) >= 2 or item["path"] == GAPS):
                    item["conflictRefs"].append(finding["id"])
    if not evidence:
        uncertainty.append("No current admitted evidence matched the question within the retrieval policy.")
    if conflicts:
        uncertainty.append("Registered findings are unresolved; retain their provenance and do not infer a resolution.")
    support_status = ("supported" if any(sub_scores.values()) or explicit_findings or conflicts or
                      any("section_intent_match" in e["relevanceSignals"] for e in evidence) else "none")
    if support_status == "none":
        evidence = []
        bytes_used = 0
    pack = {"contractVersion": CONTRACT_VERSION, "normalizedQuestion": question, "resolvedContext": context,
            "claimType": claim, "candidateSubsystems": [{"id": s, "score": sub_scores[s]} for s in candidates],
            "selectedEvidence": evidence, "conflicts": conflicts, "uncertainty": uncertainty,
            "staleSources": stale, "omittedDueToBudget": dict(sorted(omitted.items())),
            "evidenceAsOf": {"buildFingerprint": snapshot.build_fingerprint, "indexSchemaVersion": 1},
            "diagnostics": {"normalizedTokens": list(tokens), "sectionIntents": list(section_intents),
                            "supportStatus": support_status,
                            "balancedEvidenceIds": [e["evidenceId"] for e in evidence if e["reasonSelected"] == "cross-system section-intent first slot"],
                            "topEntityMatches": [{"id": e["id"], "score": s, "components": c} for s, e, c in scored_entities[:8]],
                            "relationshipExpansion": traversed, "selectedEvidenceIds": [e["evidenceId"] for e in evidence],
                            "evidenceBytes": bytes_used, "approxTokens": (bytes_used + 3) // 4,
                            "limits": LIMITS}}
    if len(json.dumps(pack, ensure_ascii=False).encode("utf-8")) > LIMITS["packBytes"]:
        raise RetrievalError("evidence pack exceeds total byte budget")
    for sid in {e["sourceId"] for e in evidence} | {c["provenance"][0]["sourceId"] for c in conflicts}:
        source = snapshot.sources[sid]
        group = "documentation" if source["contentMode"] == "sections" else "test" if source["sourceClass"] == "project_test" else "source"
        try:
            path = safe_path(snapshot.root, source["path"], group, source["maxBytes"])
            if _hash(path.read_bytes()) != source["sha256"]:
                raise RetrievalError("selected source changed during retrieval")
        except (OSError, IndexErrorClosed) as exc:
            raise RetrievalError("selected source disappeared during retrieval") from exc
    return pack
