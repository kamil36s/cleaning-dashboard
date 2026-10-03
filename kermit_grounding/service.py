"""Conservative claim checks and source-owned final composition.

This module has no provider, filesystem, network, or runtime-store access. Unknown
semantic relationships fail closed; a relevant source excerpt may be shown instead.
"""

import re
import time
import unicodedata

from kermit_model.config import configured
from kermit_model.service import generate_draft
from kermit_retrieval import retrieve


VERSION = 1
STATUSES = ("supported", "partially_supported", "contradicted", "conflicted", "unsupported")
STOP = frozenset("a an and are as at be because by can data does for from has have in is it its of on or state subsystem system the there this to uses with".split())
WORD = re.compile(r"[\w.-]+", re.UNICODE)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*])|\n+")
NEGATIVE = re.compile(r"\b(?:no|not|never|without|doesn't|don't|cannot|can't|lacks?)\b", re.I)
NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)")
FINDING_ID = re.compile(r"\b[A-Z][A-Z0-9]*-\d{2}\b", re.I)
INLINE_ID = re.compile(r"\bE[1-9]\d*\b")
ACTION = re.compile(r"\b(?:I|we|Kermit)\s+(?:ran|opened|changed|updated|queried|fetched|checked|read|wrote)\b", re.I)
SUBSYSTEMS = {"quote": {"quote", "quotable", "dummyjson", "randomquotes"},
              "finance": {"finance", "budget", "receipt"},
              "language-learning": {"language", "gemini", "anki", "stanza"},
              "weather": {"weather", "forecast", "open-meteo"},
              "cleaning": {"cleaning", "chore", "apartment"},
              "reading": {"reading", "book", "pages", "library"},
              "todo": {"todo", "subtask", "shopping"},
              "dashboard": {"dashboard", "loader", "layout"},
              "settings": {"settings", "localstorage", "preference", "mirror"},
              "central-api": {"server.py", "central", "static", "security", "origin", "port", "process"},
              "habits-app": {"habits", "habit", "supplement", "reminder", "regimen"},
              "habits-summary": {"habits", "habit", "summary", "legacy", "sobriety"},
              "habits-timeline": {"habits", "habit", "timeline", "loop"},
              "self-care": {"self-care", "self care", "selfcare", "timeline"},
              "weight-steps": {"weight", "scale", "steps", "step", "health-connect", "latest.json", "ble"},
              "diet": {"diet", "meal", "calorie", "estimate", "suggestion"},
              "sleep": {"sleep", "night", "health-connect", "ring", "watch"},
              "mental-health": {"mental", "health", "assessment", "questionnaire", "retest", "checkin", "check-in", "phq", "gad"},
              "sensors": {"sensor", "temperature", "humidity", "room", "latest.json", "readings.jsonl"},
              "ble-collector": {"ble", "collector", "advertisement", "scanner", "reconnect"}}


def _words(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    words = set()
    for raw in WORD.findall(value):
        word = raw.strip(".-")
        if word.endswith("s") and not word.endswith(("ss", "us")) and len(word) > 4:
            word = word[:-1]
        if word not in STOP and len(word) > 1:
            words.add(word)
    return words


def _clean(value):
    return re.sub(r"\s+", " ", re.sub(r"^[\s#>*\-\d.)]+", "", value)).strip()


def _sentences(value):
    if not isinstance(value, str):
        return []
    units = []
    for line in value.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or re.fullmatch(r"\|?[\s|:\-]+", line):
            continue
        if line.startswith("|"):
            cells = [re.sub(r"[*`]", "", cell.strip()) for cell in line.strip("|").split("|")]
            if len(cells) < 3 or cells[0].casefold() in ("artifact/entity", "boundary", "surface", "entry/identifier"):
                continue
            line = "; ".join(cell for cell in cells if cell)
        for part in SENTENCE.split(line):
            sentence = _clean(part)
            if len(sentence) >= 20 and not re.match(r"^(?:Subsystem|Type|Evidence|Impact):", sentence, re.I):
                units.append(sentence)
    return units


def extract_claims(answer, subjects=()):
    """Bounded, inspectable sentence/clause extraction; no model call."""
    claims = []
    names = [re.escape(name).replace(r"\-", r"[ -]") for name in subjects]
    subject = re.compile(r"\b(?:" + "|".join(names) + r")\b", re.I) if names else None
    for sentence in _sentences(answer)[:24]:
        if re.search(r"\b(?:insufficient(?: evidence)? to verify|cannot establish|not enough evidence)\b", sentence, re.I):
            continue
        # A comparison list is several claims even when the model writes one sentence.
        if subject and ":" in sentence and len(subject.findall(sentence.split(":", 1)[1])) >= 2:
            sentence = sentence.split(":", 1)[1].strip()
        parts = re.split(r";\s+|\b and (?=(?:it|the|quote|finance|language|weather|cleaning|reading|todo)\b)", sentence, flags=re.I)
        if subject:
            parts = [unit for part in parts for unit in re.split(
                r"(?:,\s*|\s+and\s+)(?=" + subject.pattern + r")", part, flags=re.I)]
        for part in parts:
            part = _clean(part)
            if part and not part.endswith(":") and not re.fullmatch(r"(?:uncertain|unknown|however|therefore)", part, re.I):
                claims.append(part)
    return claims[:24]


def _type(text, pack):
    low = text.casefold()
    if any(x in low for x in ("provider", "external", "integration", "api")):
        return "integration/provider"
    if any(x in low for x in ("canonical", "sqlite", "cache", "rebuildable", "store", "storage")):
        return "storage"
    if any(x in low for x in ("date", "threshold", "calculat", "category", "metric")):
        return "calculation"
    if any(x in low for x in ("proposed", "historical", "planned")):
        return "historical/proposed"
    return pack.get("claimType", "behavior")


def _polarity(text):
    return bool(NEGATIVE.search(text))


def _numbers(text):
    return set(NUMBER.findall(FINDING_ID.sub("", text)))


def _provider_fact(text):
    low = text.casefold()
    if re.search(r"\bexternal integration:\s*local\b", low):
        return None
    # A narrow absence (backend route or bank API) says nothing about browser
    # requests or about providers in general.
    if re.search(r"\bno\s+(?:dedicated\s+)?backend\s+integration\b|\bno\s+direct\s+bank\s+api\b", low):
        return None
    relation = re.search(r"\b(?:external|network|remote)\b.*\b(?:provider|request|fetch|integration|endpoint|api|service)\w*\b|"
                         r"\b(?:browser|direct(?:ly)?)\b.*\b(?:provider|request|fetch|cors|contact)\w*\b|"
                         r"\b(?:provider|request|fetch)\w*\b.*\b(?:external|network|remote)\b|"
                         r"\bno\s+(?:direct\s+)?provider\b", low)
    if not relation:
        return None
    negative = bool(re.search(
        r"\b(?:no|without|never|lacks?)\s+(?:(?:direct|directly|any|external|network|remote)\s+){0,3}"
        r"(?:provider|request|fetch|integration|endpoint|api|service)\w*\b|"
        r"\bnever\s+(?:uses?|makes?|contacts?|has|have)\s+(?:any\s+)?(?:external|remote|network)\s+"
        r"(?:provider|request|service|integration|api)\w*\b|"
        r"\b(?:does|do|can)\s+not\s+(?:(?:directly|ever|use|make|contact|have)\s+){0,3}"
        r"(?:external|remote|network)\s+(?:provider|request|service|integration|api)\w*\b|"
        r"\b(?:doesn't|don't|can't)\s+(?:(?:directly|ever|use|make|contact|have)\s+){0,3}"
        r"(?:external|remote|network)\s+(?:provider|request|service|integration|api)\w*\b", low))
    return not negative


def _source_candidates(pack):
    """Rank only sentences already present in selected, current evidence."""
    question = pack["normalizedQuestion"]
    terms = _words(question)
    hints = set()
    low = question.casefold()
    for trigger, additions in (("canonical", ("canonical", "sqlite", "source of truth")),
                               ("recover", ("requeue", "interrupted", "attempt", "cancel")),
                               ("interruption", ("requeue", "interrupted", "attempt", "cancel")),
                               ("reference", ("reference", "rebuildable", "canonical")),
                               ("provider", ("external", "provider", "request", "endpoint", "integration", "browser")),
                               ("weather", ("open-meteo", "forecast")),
                               ("review", ("review", "audit", "decision")),
                               ("fallback", ("fallback", "fail", "local"))):
        if trigger in low:
            hints.update(additions)
    if "what does the quote widget do" in low:
        hints.update(("random", "english", "rendered", "fetch", "fallback"))
    if "daily goal" in low and any(term in low for term in ("vary", "change", "different days")):
        hints.update(("capacity", "recovery", "overdue", "target", "completions"))
        goal_variation = True
    else:
        goal_variation = False
    quote_provider_list = "quote" in low and "which" in low and "provider" in low
    broad_provider_comparison = "pilot" in low and "provider" in low
    candidates = []
    has_scoped_evidence = any(item.get("subsystem") not in (None, "shared")
                              for item in pack["selectedEvidence"])
    for item in pack["selectedEvidence"]:
        if item.get("freshness") != "current" or item.get("factStatus") in ("proposed", "historical"):
            continue
        if has_scoped_evidence and item.get("subsystem") == "shared":
            continue
        if "GAPS_AND_CONFLICTS.md" in item.get("path", "") and not re.search(
                r"\b[A-Z][A-Z0-9]*-\d{2}\b", question, re.I):
            continue
        units = _sentences(item.get("excerpt", ""))
        if item.get("truncated"):
            units = units[:-1]
        for sentence in units:
            if len(sentence) > 480 or sentence.casefold().startswith(("status:", "reviewed ")):
                continue
            if sentence.casefold().startswith(("dashboard;", "full page;", "module;", "l0:")):
                continue
            if not any(word in low for word in ("proposed", "planned", "future", "historical")) and re.search(
                    r"\b(?:proposed|planned|future|would|should)\b", sentence, re.I):
                continue
            score = len(terms & _words(sentence)) * 3 + sum(hint in sentence.casefold() for hint in hints) * 2
            if goal_variation and re.search(r"\b(?:recovery day|ramps by|forces target)\b", sentence, re.I):
                score += 5
            if quote_provider_list and len(re.findall(r"\b(?:DummyJSON|Quotable|RandomQuotes)\b", sentence, re.I)) >= 2:
                score += 20
            if broad_provider_comparison and item.get("subsystem") == "quote" and re.search(
                    r"\bbrowser\b.*\bprovider\b", sentence, re.I):
                score += 10
            if item.get("layer") == "L1":
                score += 2
            if item.get("subsystem") in {s for s, keys in SUBSYSTEMS.items() if terms & keys}:
                score += 2
            if "canonical" in low and "canonical" in sentence.casefold():
                score += 4 if "raw archive" not in sentence.casefold() else -2
            if "provider" in low and _provider_fact(sentence) is True:
                score += 4
            if "provider" in low and "-> fixed google endpoint" in sentence.casefold():
                score += 4
            if "provider" in low and "->" in sentence and "integration" in sentence.casefold():
                score += 4
            if score >= 4:
                candidates.append((score, item["evidenceId"], sentence))
    return sorted(candidates, key=lambda row: (-row[0], row[1], len(row[2])))


def _same_subject(claim, evidence, subsystem):
    mentioned = {name for name, terms in SUBSYSTEMS.items() if _words(claim) & terms}
    if mentioned and subsystem not in mentioned:
        return False
    common = _words(claim) & _words(evidence)
    return len(common) >= 2 or (subsystem in mentioned and len(common) >= 1)


def _check_against(claim, item):
    if item.get("freshness") != "current":
        return None
    if item.get("factStatus") in ("proposed", "historical", "legacy") and not re.search(
            r"\b(?:proposed|historical|legacy|planned|previously)\b", claim, re.I):
        return None
    excerpt = item.get("excerpt", "")
    if not _same_subject(claim, excerpt, item.get("subsystem")):
        return None
    sentences = _sentences(excerpt)
    claim_words = _words(claim)
    for sentence in sentences:
        if not _same_subject(claim, sentence, item.get("subsystem")):
            continue
        common = claim_words & _words(sentence)
        relevant_clause = max(re.split(r";\s+", sentence),
                              key=lambda part: len(claim_words & _words(part)))
        if re.search(r"\b(?:implemented|currently|now)\b", claim, re.I) and re.search(
                r"\b(?:proposed|planned|future|would|should)\b", sentence, re.I):
            return "contradicted", "The cited text describes a proposal or future behavior."
        if re.search(r"\bcanonical\b", claim, re.I) and item.get("storageRole") in (
                "cache", "generated", "reference", "backup", "raw", "legacy"):
            return "contradicted", "The evidence metadata assigns a noncanonical storage role."
        cf, sf = _provider_fact(claim), _provider_fact(relevant_clause)
        if cf is not None and sf is not None and cf != sf:
            return "contradicted", "The evidence states the opposite external-provider relationship."
        if len(common) < 2:
            continue
        if re.search(r"\bcanonical\b", claim, re.I) and re.search(r"\b(?:cache|generated|rebuildable|reference)\b", claim, re.I):
            if re.search(r"\b(?:cache|generated|rebuildable|reference)\b", sentence, re.I) and re.search(r"\b(?:not|separate|secondary)\b", sentence, re.I):
                return "contradicted", "The source distinguishes canonical state from derived or reference data."
        cn, sn = _numbers(claim), _numbers(sentence)
        if cn and sn and cn != sn and len(common) >= 3:
            return "contradicted", "The numeric values differ in the relevant source sentence."
        polarity_terms = claim_words - {"no", "not", "never", "without", "cannot", "lack"}
        if (_polarity(claim) != _polarity(relevant_clause) and len(common) >= 3 and polarity_terms
                and len(common) / len(polarity_terms) >= 0.75):
            return "contradicted", "The source sentence has opposite polarity."
        claim_paths = {path.casefold() for path in re.findall(r"[\w./-]+\.sqlite\b", claim, re.I)}
        if (claim_paths and "canonical" in claim.casefold() and "canonical" in sentence.casefold()
                and claim_paths <= {path.casefold() for path in re.findall(r"[\w./-]+\.sqlite\b", sentence, re.I)}
                and _polarity(claim) == _polarity(sentence)):
            return "supported", "The canonical SQLite path is stated directly in the source."
        relation_words = {"external", "network", "remote", "browser", "direct", "directly", "provider",
                          "request", "fetch", "integration", "endpoint", "api", "service", "use", "using",
                          "uses", "make", "makes", "contact", "contacts", "no", "not", "never", "without"}
        subject_words = set().union(*(terms for terms in SUBSYSTEMS.values()))
        if (cf is not None and sf is not None and cf == sf and len(common) >= 2
                and (claim_words - relation_words - subject_words) <= _words(sentence)):
            return "supported", "Explicit provider relationship in the bound evidence."
        normalized_claim = " ".join(WORD.findall(claim.casefold()))
        normalized_source = " ".join(WORD.findall(sentence.casefold()))
        if normalized_claim in normalized_source or (claim_words and claim_words <= _words(sentence)
                                                       and not (cn - sn) and _polarity(claim) == _polarity(sentence)):
            return "supported", "The claim is stated directly in the bound evidence."
    return None


def _bind(claim, draft_ids, by_id):
    claim_words = _words(claim)
    mentioned = {name for name, terms in SUBSYSTEMS.items() if claim_words & terms}
    ranked = []
    for evidence_id in by_id:
        item = by_id[evidence_id]
        if mentioned and item.get("subsystem") not in mentioned:
            continue
        overlap = len(claim_words & _words(item.get("excerpt", "")))
        if overlap >= 2 or (mentioned and overlap >= 1 and _provider_fact(claim) is not None):
            ranked.append((overlap, evidence_id in draft_ids, evidence_id))
    ranked.sort(key=lambda pair: (-pair[0], -pair[1], pair[2]))
    return [eid for _, _, eid in ranked[:4]]


def _citation(item):
    return {"evidenceId": item["evidenceId"], "path": item["path"], "locator": item["locator"],
            "sourceSha256": item["sourceSha256"], "factStatus": item["factStatus"],
            "storageRole": item.get("storageRole"), "freshness": item["freshness"]}


def _conflicts(pack, evidence_ids):
    by_id = {item["evidenceId"]: item for item in pack["selectedEvidence"]}
    result = []
    requested = set(re.findall(r"\b[A-Z][A-Z0-9]*-\d{2}\b", pack.get("normalizedQuestion", ""), re.I))
    for conflict in pack.get("conflicts", []):
        cid = conflict["id"]
        register_id = conflict.get("registerEvidenceId")
        register = by_id.get(register_id)
        if not (register and register.get("path") == "docs/kermit/knowledge/GAPS_AND_CONFLICTS.md"
                and register.get("freshness") == "current"
                and register.get("locator", {}).get("heading") == cid.removeprefix("conflict:")
                and conflict["description"] in register.get("excerpt", "")):
            register_id = None
        if cid.removeprefix("conflict:") not in requested and not register_id and not any(
                cid in item.get("conflictRefs", []) for item in by_id.values()):
            continue
        sides = []
        for key, label in (("sideA", "A"), ("sideB", "B")):
            reviewed = conflict.get(key, {})
            valid = []
            for ref in reviewed.get("expectedSourceRefs", []):
                for eid in reviewed.get("selectedEvidenceIds", []):
                    item = by_id.get(eid)
                    if (item and item.get("freshness") == "current" and item.get("sourceId") == ref.get("sourceId")
                            and item.get("path") == ref.get("path") and item.get("sourceSha256") == ref.get("sourceSha256")
                            and item.get("locator", {}).get("lineStart") == ref.get("lineStart")
                            and item.get("locator", {}).get("lineEnd") == ref.get("lineEnd")
                            and ref.get("anchor") in item.get("excerpt", "") and eid not in valid):
                        valid.append(eid)
            if len(valid) != reviewed.get("requiredRefCount", len(reviewed.get("expectedSourceRefs", []))):
                valid = []
            sides.append({"side": label, "text": reviewed.get("description", ""),
                          "expectedSourceRefs": reviewed.get("expectedSourceRefs", []),
                          "requiredRefCount": reviewed.get("requiredRefCount", len(reviewed.get("expectedSourceRefs", []))),
                          "selectedEvidenceIds": valid})
        category = conflict.get("category", "UNKNOWN_BEHAVIOR")
        if category in ("TEST_COVERAGE_GAP", "UNKNOWN_BEHAVIOR"):
            status = "not_a_two_sided_conflict"
        elif sides[0]["selectedEvidenceIds"] and sides[1]["selectedEvidenceIds"]:
            status = ("independently_cited" if category in ("FACTUAL_CONFLICT", "DOCUMENTATION_DRIFT")
                      else "not_a_two_sided_conflict")
        else:
            status = "register_summary_only" if register_id else "insufficient_primary_evidence"
        result.append({"conflictId": cid, "description": conflict["description"],
                       "type": category, "originalType": conflict["type"], "evidenceSides": sides,
                       "registerEvidenceId": register_id, "status": status})
    return result


def ground(pack, draft, *, trace_sink=None):
    """Validate one already generated draft. Unknown semantic support is never accepted."""
    start = time.monotonic()
    if pack.get("contractVersion") != 1 or not isinstance(pack.get("selectedEvidence"), list):
        raise ValueError("invalid Phase 4 pack")
    by_id = {item["evidenceId"]: item for item in pack["selectedEvidence"]}
    if len(by_id) != len(pack["selectedEvidence"]):
        raise ValueError("duplicate evidence ID")
    if any(item.get("freshness") != "current" for item in by_id.values()):
        raise ValueError("stale evidence cannot enter a GroundedAnswer")
    ids = draft.get("citedEvidenceIds", [])
    if not isinstance(ids, list) or len(ids) != len(set(ids)) or any(eid not in by_id for eid in ids):
        raise ValueError("unknown draft evidence ID")
    claims = []
    accepted = []
    for index, sentence in enumerate(extract_claims(
            draft.get("answer", ""), (s["id"] for s in pack.get("candidateSubsystems", []))), 1):
        bound = _bind(sentence, ids, by_id)
        checks = [(eid, _check_against(sentence, by_id[eid])) for eid in bound]
        contradiction = next(((eid, result[1]) for eid, result in checks if result and result[0] == "contradicted"), None)
        support = [(eid, result[1]) for eid, result in checks if eid in ids and result and result[0] == "supported"]
        illegal_ids = set(INLINE_ID.findall(sentence)) - set(by_id)
        if illegal_ids or ACTION.search(sentence):
            status, reason = "unsupported", "The draft contains an unknown evidence ID or action claim."
        elif contradiction:
            status, reason = "contradicted", contradiction[1]
        elif support:
            status, reason = "supported", support[0][1]
        else:
            status, reason = "unsupported", "No bound evidence directly proves this wording."
        relevant_conflicts = sorted({ref for eid in bound for ref in by_id[eid].get("conflictRefs", [])})
        if status == "supported" and relevant_conflicts:
            status, reason = "conflicted", "A registered finding qualifies this claim."
        evidence_ids = [eid for eid, _ in support] if status in ("supported", "conflicted") else bound
        claim = {"claimId": f"C{index}", "text": sentence, "type": _type(sentence, pack),
                 "evidenceIds": evidence_ids, "supportStatus": status, "supportReason": reason,
                 "conflictIds": relevant_conflicts}
        if trace_sink is not None:
            trace_sink({"claimId": claim["claimId"], "text": sentence, "boundEvidenceIds": bound,
                        "evidenceChecks": [{"evidenceId": eid, "decision": result} for eid, result in checks],
                        "decision": status, "reason": reason})
        claims.append(claim)
        if status == "supported":
            accepted.append(claim)
    conflict_rows = _conflicts(pack, list(by_id))
    # Synthesis is deterministic. Only accepted draft claims and verbatim reviewed
    # evidence sentences can become factual output; discarded draft text is never used.
    lines = []
    used = []
    displayed = []
    variation_question = ("daily goal" in pack["normalizedQuestion"].casefold() and re.search(
        r"\b(?:vary|change|different days)\b", pack["normalizedQuestion"], re.I))
    if variation_question:
        accepted = [claim for claim in accepted if re.search(
            r"\b(?:because|when|if|starts|ramps|caps|forces|bounded|based on|plus|depends|changes)\b",
            claim["text"], re.I)]
    quote_provider_list = ("quote" in pack["normalizedQuestion"].casefold() and
                           "which" in pack["normalizedQuestion"].casefold() and
                           "provider" in pack["normalizedQuestion"].casefold())
    if quote_provider_list:
        accepted = [claim for claim in accepted if re.search(
            r"\b(?:DummyJSON|Quotable|RandomQuotes)\b", claim["text"], re.I)]
    for claim in accepted[:4]:
        eid = claim["evidenceIds"][0]
        lines.append(f'{claim["text"].rstrip(".")} [{eid}].')
        used.append(eid)
        displayed.append(claim["claimId"])
    directly_requested_finding = bool(re.search(r"\b[A-Z][A-Z0-9]*-\d{2}\b", pack["normalizedQuestion"], re.I))
    if not lines and ids and not directly_requested_finding:
        seen_subsystems = set()
        seen_sentences = set()
        per_evidence = {}
        broad = not any(s.get("score", 0) > 0 for s in pack.get("candidateSubsystems", []))
        for _, eid, chosen in _source_candidates(pack):
            subsystem = by_id[eid].get("subsystem")
            if broad and subsystem in seen_subsystems:
                continue
            if chosen in seen_sentences or per_evidence.get(eid, 0) >= 2:
                continue
            label = (subsystem or "Source").replace("-", " ").title()
            lines.append(f'{label}: {chosen.rstrip(".")} [{eid}].')
            used.append(eid)
            seen_subsystems.add(subsystem)
            seen_sentences.add(chosen)
            per_evidence[eid] = per_evidence.get(eid, 0) + 1
            claims.append({"claimId": f"S{len(seen_sentences)}", "text": f"{label}: {chosen}", "type": _type(chosen, pack),
                           "evidenceIds": [eid], "supportStatus": "supported",
                           "supportReason": "Deterministic excerpt from the selected evidence.",
                           "conflictIds": by_id[eid].get("conflictRefs", [])})
            displayed.append(claims[-1]["claimId"])
            narrow_limit = 1 if pack["normalizedQuestion"].casefold().startswith("where does ") else 2
            if len(lines) >= (4 if broad else narrow_limit):
                break
    for conflict in conflict_rows:
        def finding_line(sentence, ids, reason):
            lines.append(sentence.rstrip(".") + (" " + " ".join(f"[{eid}]" for eid in ids) if ids else "") + ".")
            used.extend(ids)
            claims.append({"claimId": f'F{len(claims) + 1}', "text": sentence, "type": "limitation",
                           "evidenceIds": ids, "supportStatus":
                           ("conflicted" if conflict["type"] in ("FACTUAL_CONFLICT", "DOCUMENTATION_DRIFT")
                            else "supported") if ids else "unsupported",
                           "supportReason": reason, "conflictIds": [conflict["conflictId"]]})
            displayed.append(claims[-1]["claimId"] if ids else None)
        register_id = conflict["registerEvidenceId"]
        if register_id:
            finding_line(f'{conflict["conflictId"]} is a registered {conflict["type"]} finding', [register_id],
                         "Reviewed finding register metadata.")
        for side in conflict["evidenceSides"]:
            ids_for_side = side["selectedEvidenceIds"]
            if ids_for_side:
                finding_line(f'{conflict["conflictId"]} side {side["side"]}: {side["text"]}', ids_for_side,
                             "Reviewed primary side binding in selected evidence.")
        if conflict["status"] == "register_summary_only":
            lines.append(f'{conflict["conflictId"]}: The register summarizes this discrepancy, but selected primary evidence does not establish both sides independently.')
            displayed.append(None)
        elif conflict["status"] == "insufficient_primary_evidence":
            lines.append(f'{conflict["conflictId"]}: Independent primary evidence for both sides is insufficient.')
            displayed.append(None)
        elif conflict["type"] == "TEST_COVERAGE_GAP" and register_id:
            finding_line(f'{conflict["conflictId"]}: Focused test coverage was not found in the reviewed inventory',
                         [register_id], "Reviewed test inventory gap, not an opposite factual side.")
    uncertainty = list(dict.fromkeys(pack.get("uncertainty", []) + draft.get("uncertainty", [])))[:8]
    if any(c["status"] == "register_summary_only" for c in conflict_rows):
        uncertainty.append("At least one finding lacks independently selected primary evidence for both sides.")
    rejected = sum(c["supportStatus"] in ("unsupported", "contradicted") for c in claims)
    if rejected:
        uncertainty.append(f"{rejected} draft claim(s) lacked direct support and were omitted.")
    if not lines:
        lines = ["The supplied evidence is insufficient to verify an answer."]
        displayed = [None]
    approved = {claim["claimId"]: claim for claim in claims
                if claim["supportStatus"] in ("supported", "conflicted")}
    if len(lines) != len(displayed) or any(claim_id is not None and claim_id not in approved for claim_id in displayed):
        raise ValueError("final sentence lacks an approved claim")
    citations = [_citation(by_id[eid]) for eid in dict.fromkeys(used)]
    result = {"contractVersion": VERSION, "answer": "\n".join(lines), "claims": claims,
              "citations": citations, "uncertainty": uncertainty[:8], "conflicts": conflict_rows,
              "groundingStatus": ("conflicted" if any(c["type"] in ("FACTUAL_CONFLICT", "DOCUMENTATION_DRIFT")
                                                       for c in conflict_rows) else
                                  "grounded" if citations else "insufficient_evidence"),
              "evidenceAsOf": pack["evidenceAsOf"],
              "displayedClaimIds": displayed,
              "groundingLatencyMs": int((time.monotonic() - start) * 1000)}
    return result


def ask_grounded(question, *, profile="normal", provider=None, allow_memory_pressure=False, explain=False):
    """Phase 4 retrieval -> Phase 5 draft -> Phase 6 final answer."""
    config = configured(profile, provider)
    pack = retrieve({"contractVersion": 1, "question": question})
    draft = generate_draft(pack, config=config, allow_memory_pressure=allow_memory_pressure, explain=explain)
    if draft["status"] not in ("draft", "insufficient_evidence"):
        return {"contractVersion": VERSION, "answer": draft["answer"], "claims": [], "citations": [],
                "uncertainty": draft.get("uncertainty", []), "conflicts": [], "groundingStatus": draft["status"],
                "evidenceAsOf": pack["evidenceAsOf"], "groundingLatencyMs": 0,
                "draftStatus": draft["status"], "draftLatencyMs": draft["latencyMs"],
                "resource": draft.get("resource")}
    result = ground(pack, draft)
    result.update(draftStatus=draft["status"], draftLatencyMs=draft["latencyMs"],
                  provider=draft["provider"], model=draft["model"], profile=draft["profile"])
    if explain:
        result["diagnostics"] = draft.get("diagnostics")
    return result
