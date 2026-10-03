"""Bounded, read-only Phase 8 drift diagnostics for reviewed static knowledge."""

import ast
import hashlib
import json
from pathlib import Path
import re

from .builder import PACKS, safe_path, IndexErrorClosed


PACK_REF = re.compile(r"^\| `([^`]+)` \| `([^`]+)` \|$", re.M)
WIDGET = re.compile(r'data-widget\s*=\s*[\'\"]([^\'\"]+)[\'\"]')
LOADER = re.compile(r'^  (?:"([^"]+)"|([a-z][a-z0-9-]*)):\s*(?:async\s*)?\(', re.M)
API = re.compile(r"^/api/([a-z][a-z0-9-]*)")
MAX_READ = 2_000_000


def _read(root, relative):
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise OSError(f"missing or unsafe path: {relative}")
    if path.stat().st_size > MAX_READ:
        raise OSError(f"oversized path: {relative}")
    return path.read_bytes()


def _api_domains(root):
    domains = set()
    for relative in ("server.py", "training_runtime.py", "network_monitor/api.py"):
        tree = ast.parse(_read(root, relative).decode("utf-8-sig"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                match = API.match(node.value)
                if match:
                    domains.add(match.group(1))
    return domains


def _pack_refs(content):
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    section = content.split("## Checked implementation references", 1)
    if len(section) < 2:
        return []
    body = section[1].split("\n## ", 1)[0]
    return PACK_REF.findall(body)


def coverage_check(root, manifest, output):
    """Return sorted findings; never create, repair, admit, or rebuild anything."""
    root = Path(root).resolve()
    findings = set()
    spec = json.loads(_read(root, Path(manifest).resolve().relative_to(root).as_posix()).decode("utf-8"))
    admissions = {item["path"]: item for item in spec["entries"]}
    index_path = Path(output).resolve()
    if not index_path.is_relative_to(root):
        raise IndexErrorClosed("index path is outside repository")
    snapshots = {}
    source_file = index_path / "sources.jsonl"
    if not source_file.is_file() or source_file.stat().st_size > 20_000_000:
        findings.add(("index_missing", "sources.jsonl"))
    else:
        for line in source_file.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            snapshots[row["path"]] = row["sha256"]

    current = {}
    for relative, item in sorted(admissions.items()):
        try:
            policy = spec["defaults"][item["group"]]
            path = safe_path(root, relative, item["group"], policy["maxBytes"])
            content = path.read_bytes()
            current[relative] = hashlib.sha256(content).hexdigest()
        except (OSError, IndexErrorClosed) as exc:
            findings.add(("admitted_source_missing", relative))
            continue
        if relative not in snapshots:
            findings.add(("index_source_missing", relative))
        elif snapshots[relative] != current[relative]:
            findings.add(("admitted_source_changed", relative))

    for relative in sorted(snapshots.keys() - admissions.keys()):
        findings.add(("index_source_not_admitted", relative))

    for slug in PACKS:
        pack = f"docs/kermit/knowledge/subsystems/{slug}.md"
        if pack not in admissions:
            continue
        try:
            content = _read(root, pack).decode("utf-8-sig")
        except (OSError, UnicodeError):
            findings.add(("validated_pack_missing", pack))
            continue
        # Legacy packs predate the checked-marker table. Their exact admitted
        # ownership still identifies a stale pack after a source fingerprint edit.
        for relative, item in admissions.items():
            if item["subsystem"] == slug or f"`{relative}`" in content or f"`{relative}::" in content:
                if snapshots.get(relative) != current.get(relative):
                    findings.add(("validated_pack_source_changed", f"{pack}: {relative}"))
        for relative, marker in _pack_refs(content):
            if relative not in admissions:
                findings.add(("pack_reference_not_admitted", f"{pack}: {relative}"))
            try:
                source = _read(root, relative).decode("utf-8-sig")
            except (OSError, UnicodeError):
                findings.add(("referenced_source_missing", f"{pack}: {relative}"))
                findings.add(("validated_pack_source_changed", f"{pack}: {relative}"))
                continue
            if marker not in source:
                findings.add(("pack_reference_missing_marker", f"{pack}: {relative}: {marker}"))
            if snapshots.get(relative) != current.get(relative):
                findings.add(("validated_pack_source_changed", f"{pack}: {relative}"))
        if snapshots.get(pack) != current.get(pack):
            findings.add(("validated_pack_source_changed", pack))

    ledger = _read(root, "docs/kermit/knowledge/COVERAGE.md").decode("utf-8-sig")
    rows = ledger.split("## Coverage ledger", 1)[-1].split("## Independently reviewable batches", 1)[0]
    markup = _read(root, "index.html").decode("utf-8-sig")
    loader = _read(root, "js/dashboard-widget-loader.js").decode("utf-8-sig")
    registered = set(WIDGET.findall(markup))
    loader_keys = {a or b for a, b in LOADER.findall(loader.split("const widgetLoaders = {", 1)[-1].split("\n};", 1)[0])}
    for key in sorted(registered - loader_keys):
        findings.add(("widget_missing_loader", key))
    for key in sorted(loader_keys - registered):
        findings.add(("loader_missing_widget", key))
    for key in sorted(registered & loader_keys):
        if f"`{key}`" not in rows:
            findings.add(("widget_missing_coverage", key))

    domains = _api_domains(root)
    inventory = ledger.split("## API domain inventory", 1)
    listed = set(re.findall(r"`/api/([a-z][a-z0-9-]*)`", inventory[1].split("\n## ", 1)[0])) if len(inventory) == 2 else set()
    for domain in sorted(domains - listed):
        findings.add(("api_domain_missing_coverage", domain))
    for domain in sorted(listed - domains):
        findings.add(("api_domain_not_implemented", domain))
    return {"status": "current" if not findings else "stale", "widgetCount": len(registered & loader_keys),
            "apiDomainCount": len(domains), "admittedCount": len(admissions),
            "findings": [{"code": code, "subject": subject} for code, subject in sorted(findings)]}
