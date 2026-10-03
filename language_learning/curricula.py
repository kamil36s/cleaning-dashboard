"""Versioned, manifest-backed practical vocabulary curricula.

Pack definitions are tracked reference-like artifacts.  User progress is derived in
bounded batches from canonical VocabularyLemma/LemmaKnowledge rows and is never
persisted here.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .analysis.base import normalize_lookup
from .errors import LanguageNotFoundError, LanguageValidationError
from .store import canonical_json


MANIFEST_VERSION = "language.curriculum-pack-manifest/v1"
CURRICULUM_POLICY_VERSION = "language.curriculum-policy/v1"
DENOMINATOR_POLICY_VERSION = "language.curriculum-denominator/v1"
PROGRESS_POLICY_VERSION = "language.curriculum-progress/v1"
MAPPING_POLICY_VERSION = "language.curriculum-reference-mapping/v1"
PACK_STATUSES = frozenset({"DRAFT", "ACTIVE", "ARCHIVED"})
REVIEW_STATES = frozenset({"APPROVED", "DRAFT", "REJECTED"})
MAPPING_STATES = frozenset({"MAPPED", "AMBIGUOUS", "UNRESOLVED", "EXCLUDED"})
PRIORITIES = frozenset({"CORE", "USEFUL", "EXTENDED"})
PACK_ID_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
MAX_PACK_ITEMS = 2000


def curriculum_fingerprint(manifest: dict[str, Any]) -> str:
    """Return the stable semantic fingerprint, excluding generated summaries."""

    pack = dict(manifest.get("pack") or {})
    for key in ("fingerprint", "itemCount", "mappingCounts", "denominatorCounts"):
        pack.pop(key, None)
    payload = {
        "schemaVersion": manifest.get("schemaVersion"),
        "pack": pack,
        "source": manifest.get("source"),
        "mappingSnapshot": manifest.get("mappingSnapshot"),
        "items": manifest.get("items"),
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _quality_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    mapping = {state: 0 for state in MAPPING_STATES}
    review = {state: 0 for state in REVIEW_STATES}
    for item in items:
        mapping[str(item["mappingState"])] += 1
        review[str(item["reviewState"])] += 1
    eligible = sum(
        item["reviewState"] == "APPROVED" and item["mappingState"] == "MAPPED"
        for item in items
    )
    return {
        "sourceItemTotal": len(items),
        "approvedTotal": review["APPROVED"],
        "draftTotal": review["DRAFT"],
        "rejectedTotal": review["REJECTED"],
        "mappedTotal": mapping["MAPPED"],
        "ambiguousTotal": mapping["AMBIGUOUS"],
        "unresolvedTotal": mapping["UNRESOLVED"],
        "excludedTotal": mapping["EXCLUDED"],
        "eligibleDenominator": eligible,
    }


def validate_curriculum_manifest(manifest: Any, *, require_fingerprint: bool = True) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise LanguageValidationError("Curriculum manifest must be an object", code="invalid_curriculum_manifest")
    if manifest.get("schemaVersion") != MANIFEST_VERSION:
        raise LanguageValidationError("Curriculum manifest version is unsupported", code="invalid_curriculum_manifest")
    pack = manifest.get("pack")
    source = manifest.get("source")
    snapshot = manifest.get("mappingSnapshot")
    items = manifest.get("items")
    if not isinstance(pack, dict) or not isinstance(source, dict) or not isinstance(snapshot, dict) or not isinstance(items, list):
        raise LanguageValidationError("Curriculum manifest sections are invalid", code="invalid_curriculum_manifest")
    pack_id = str(pack.get("id") or "")
    if not PACK_ID_RE.fullmatch(pack_id):
        raise LanguageValidationError("Curriculum pack id is invalid", details=["pack.id"])
    try:
        version = int(pack.get("version"))
    except (TypeError, ValueError) as exc:
        raise LanguageValidationError("Curriculum pack version must be a positive integer") from exc
    if version < 1 or pack.get("language") != "nb" or pack.get("status") not in PACK_STATUSES:
        raise LanguageValidationError("Curriculum pack identity/status is invalid", code="invalid_curriculum_manifest")
    for field in ("slug", "name", "description", "category", "sourceType", "reviewState", "releasedDate"):
        if not isinstance(pack.get(field), str) or not str(pack[field]).strip():
            raise LanguageValidationError(f"Curriculum pack {field} is required", details=[f"pack.{field}"])
    if pack.get("curriculumPolicyVersion") != CURRICULUM_POLICY_VERSION:
        raise LanguageValidationError("Curriculum policy version is invalid", details=["pack.curriculumPolicyVersion"])
    if pack.get("denominatorPolicyVersion") != DENOMINATOR_POLICY_VERSION:
        raise LanguageValidationError("Curriculum denominator policy version is invalid")
    if pack.get("progressPolicyVersion") != PROGRESS_POLICY_VERSION:
        raise LanguageValidationError("Curriculum progress policy version is invalid")
    for field in ("id", "provider", "name", "version", "url", "license", "licenseUrl", "attribution", "membershipBasis"):
        if not isinstance(source.get(field), str) or not str(source[field]).strip():
            raise LanguageValidationError(f"Curriculum source {field} is required", details=[f"source.{field}"])
    if snapshot.get("mappingPolicyVersion") != MAPPING_POLICY_VERSION:
        raise LanguageValidationError("Curriculum mapping policy version is invalid")
    for field in ("resolverRuleVersion", "sourceArtifactSha256", "sourceArtifactLastModified", "mappedDate"):
        if not isinstance(snapshot.get(field), str) or not str(snapshot[field]).strip():
            raise LanguageValidationError(
                f"Curriculum mapping snapshot {field} is required",
                details=[f"mappingSnapshot.{field}"],
            )
    if not isinstance(snapshot.get("referenceSchemaVersion"), int) or snapshot["referenceSchemaVersion"] < 1:
        raise LanguageValidationError("Reference schema version is invalid")
    if not isinstance(snapshot.get("referenceFingerprint"), str) or not snapshot["referenceFingerprint"].startswith("sha256:"):
        raise LanguageValidationError("Reference fingerprint is required")
    if not 1 <= len(items) <= MAX_PACK_ITEMS:
        raise LanguageValidationError("Curriculum items must contain 1 to 2000 rows", details=["items"])

    membership_ids: set[str] = set()
    source_ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise LanguageValidationError("Curriculum item must be an object", details=[f"items[{index}]"])
        membership_id = str(item.get("membershipId") or "")
        source_id = str(item.get("sourceMembershipId") or "")
        display = str(item.get("displayTerm") or "").strip()
        normalized = str(item.get("normalizedLookup") or "")
        if not re.fullmatch(r"[a-f0-9]{32}", membership_id):
            raise LanguageValidationError("Curriculum membership id is invalid", details=[f"items[{index}].membershipId"])
        if not source_id or not display or normalized != normalize_lookup(display):
            raise LanguageValidationError("Curriculum item identity is invalid", details=[f"items[{index}]"])
        if membership_id in membership_ids or source_id in source_ids:
            raise LanguageValidationError("Curriculum item identity is duplicated", code="duplicate_curriculum_item")
        membership_ids.add(membership_id)
        source_ids.add(source_id)
        review = item.get("reviewState")
        mapping = item.get("mappingState")
        if review not in REVIEW_STATES or mapping not in MAPPING_STATES:
            raise LanguageValidationError("Curriculum review/mapping state is invalid", details=[f"items[{index}]"])
        if (
            item.get("priority") not in PRIORITIES
            or isinstance(item.get("weight"), bool)
            or not isinstance(item.get("weight"), (int, float))
            or float(item["weight"]) <= 0
        ):
            raise LanguageValidationError("Curriculum priority/weight is invalid", details=[f"items[{index}]"])
        for field in ("mappingBasis", "provenanceClass"):
            if not isinstance(item.get(field), str) or not str(item[field]).strip():
                raise LanguageValidationError(
                    f"Curriculum item {field} is required", details=[f"items[{index}].{field}"]
                )
        if mapping == "MAPPED":
            unit = item.get("referenceUnit")
            if not isinstance(unit, dict) or not all(unit.get(key) for key in ("id", "stableKey", "canonicalForm", "normalizedForm")):
                raise LanguageValidationError("Mapped curriculum item requires a reference unit", details=[f"items[{index}].referenceUnit"])
        if mapping == "AMBIGUOUS" and not item.get("mappingCandidates"):
            raise LanguageValidationError("Ambiguous curriculum item requires candidates", details=[f"items[{index}].mappingCandidates"])
        if mapping == "EXCLUDED" and review == "APPROVED":
            raise LanguageValidationError("Excluded curriculum item cannot be approved", details=[f"items[{index}]"])

    result = deepcopy(manifest)
    expected = curriculum_fingerprint(result)
    supplied = pack.get("fingerprint")
    if require_fingerprint and supplied != expected:
        raise LanguageValidationError("Curriculum fingerprint does not match semantic content", code="curriculum_fingerprint_mismatch")
    result["pack"]["fingerprint"] = expected
    result["pack"]["itemCount"] = len(items)
    result["pack"]["denominatorCounts"] = _quality_counts(items)
    return result


class CurriculumService:
    """Read-only manifest loader plus derived canonical-user progress."""

    def __init__(
        self,
        store: Any,
        *,
        manifest_directory: str | Path | None = None,
        reference_service: Any | None = None,
        dictionary_provider: Any | None = None,
    ) -> None:
        self.store = store
        self.manifest_directory = Path(manifest_directory or Path(__file__).with_name("curriculum_packs"))
        self.reference_service = reference_service
        self.dictionary_provider = dictionary_provider
        self._packs: dict[tuple[str, int], dict[str, Any]] | None = None
        self._catalog: dict[str, Any] | None = None

    def attach_reference_service(self, service: Any | None) -> None:
        self.reference_service = service

    def _load(self) -> None:
        if self._packs is not None:
            return
        packs: dict[tuple[str, int], dict[str, Any]] = {}
        for path in sorted(self.manifest_directory.glob("*.json")):
            if path.name in {"manifest.schema.json", "catalog.json"}:
                continue
            manifest = validate_curriculum_manifest(json.loads(path.read_text(encoding="utf-8")))
            identity = (str(manifest["pack"]["id"]), int(manifest["pack"]["version"]))
            if identity in packs:
                raise LanguageValidationError("Duplicate curriculum pack version", code="duplicate_curriculum_pack")
            packs[identity] = manifest
        catalog_path = self.manifest_directory / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else {"schemaVersion": "language.curriculum-catalog/v1", "unavailablePacks": []}
        if catalog.get("schemaVersion") != "language.curriculum-catalog/v1" or not isinstance(catalog.get("unavailablePacks"), list):
            raise LanguageValidationError("Curriculum catalog is invalid", code="invalid_curriculum_catalog")
        catalog_ids: set[str] = set()
        for index, item in enumerate(catalog["unavailablePacks"]):
            if (
                not isinstance(item, dict)
                or not PACK_ID_RE.fullmatch(str(item.get("id") or ""))
                or item.get("status") != "UNAVAILABLE"
                or any(not isinstance(item.get(field), str) or not item[field].strip() for field in ("name", "category", "reason"))
            ):
                raise LanguageValidationError(
                    "Unavailable curriculum catalog item is invalid",
                    details=[f"unavailablePacks[{index}]"],
                )
            if item["id"] in catalog_ids or any(pack_id == item["id"] for pack_id, _ in packs):
                raise LanguageValidationError("Curriculum catalog id is duplicated", code="duplicate_curriculum_pack")
            catalog_ids.add(item["id"])
        self._packs, self._catalog = packs, catalog

    def pack(self, pack_id: str, version: int | str | None = None) -> dict[str, Any]:
        self._load()
        assert self._packs is not None
        candidates = [value for (candidate_id, _), value in self._packs.items() if candidate_id == pack_id]
        if not candidates:
            raise LanguageNotFoundError("Curriculum pack was not found", code="curriculum_pack_not_found")
        if version is None:
            active = [value for value in candidates if value["pack"]["status"] == "ACTIVE"]
            return max(active or candidates, key=lambda value: int(value["pack"]["version"]))
        try:
            key = (pack_id, int(version))
        except (TypeError, ValueError) as exc:
            raise LanguageValidationError("Curriculum pack version is invalid") from exc
        if key not in self._packs:
            raise LanguageNotFoundError("Curriculum pack version was not found", code="curriculum_pack_version_not_found")
        return self._packs[key]

    def active_packs(self) -> list[dict[str, Any]]:
        self._load()
        assert self._packs is not None
        return sorted(
            (value for value in self._packs.values() if value["pack"]["status"] == "ACTIVE"),
            key=lambda value: (int(value["pack"].get("displayOrder") or 999), value["pack"]["name"]),
        )

    @staticmethod
    def _eligible_items(pack: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item for item in pack["items"]
            if item["reviewState"] == "APPROVED" and item["mappingState"] == "MAPPED"
        ]

    def _knowledge_index(self, profile_id: str, packs: Iterable[dict[str, Any]]) -> dict[tuple[str, str | None], list[dict[str, Any]]]:
        identities = []
        seen = set()
        for pack in packs:
            for item in self._eligible_items(pack):
                unit = item["referenceUnit"]
                identity = (str(unit["normalizedForm"]), unit.get("partOfSpeech"))
                if identity not in seen:
                    seen.add(identity)
                    identities.append({"normalizedLookup": identity[0], "partOfSpeech": identity[1]})
        rows = self.store.curriculum_knowledge_snapshot(profile_id, identities)
        index: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
        for row in rows:
            index.setdefault((str(row["lemma_normalized"]), row.get("part_of_speech")), []).append(row)
        return index

    @staticmethod
    def _user_for_item(item: dict[str, Any], index: dict[tuple[str, str | None], list[dict[str, Any]]]) -> dict[str, Any]:
        if item["reviewState"] != "APPROVED" or item["mappingState"] != "MAPPED":
            return {"state": "NOT_ELIGIBLE", "userLemmaId": None, "acquired": False}
        unit = item["referenceUnit"]
        normalized, pos = str(unit["normalizedForm"]), unit.get("partOfSpeech")
        rows = index.get((normalized, pos), [])
        if not rows and pos is None:
            candidates = [row for (value, _), matches in index.items() if value == normalized for row in matches]
            rows = candidates if len(candidates) == 1 else []
        row = rows[0] if len(rows) == 1 else None
        state = str(row.get("knowledge_status") or "NEW") if row else "UNSEEN"
        return {
            "state": state,
            "userLemmaId": str(row["id"]) if row else None,
            "acquired": state in {"KNOWN", "MASTERED"},
            "disposition": row.get("disposition") if row else None,
        }

    def _progress(self, pack: dict[str, Any], index: dict[tuple[str, str | None], list[dict[str, Any]]], *, include_items: bool) -> dict[str, Any]:
        counts = dict(pack["pack"]["denominatorCounts"])
        states = {state: 0 for state in ("UNSEEN", "NEW", "LEARNING", "KNOWN", "MASTERED")}
        item_payloads = []
        for item in pack["items"]:
            user = self._user_for_item(item, index)
            if user["state"] in states:
                states[user["state"]] += 1
            if include_items:
                item_payloads.append({**deepcopy(item), "user": user})
        completed = states["KNOWN"] + states["MASTERED"]
        denominator = counts["eligibleDenominator"]
        payload = {
            "completed": completed,
            "progressPercent": round(completed * 100 / denominator, 1) if denominator else 0.0,
            "stateCounts": states,
            "completionRule": "KNOWN_OR_MASTERED",
            "completionSemantics": "KNOWN and MASTERED count as acquired; LEARNING, NEW and UNSEEN do not. KNOWN and MASTERED remain separate states.",
            "progressPolicyVersion": PROGRESS_POLICY_VERSION,
            "denominatorPolicyVersion": DENOMINATOR_POLICY_VERSION,
            **counts,
        }
        if include_items:
            payload["items"] = item_payloads
        return payload

    @staticmethod
    def _pack_public(pack: dict[str, Any]) -> dict[str, Any]:
        return {**deepcopy(pack["pack"]), "source": deepcopy(pack["source"]), "mappingSnapshot": deepcopy(pack["mappingSnapshot"])}

    def landing(self, profile_id: str) -> dict[str, Any]:
        packs = self.active_packs()
        index = self._knowledge_index(profile_id, packs)
        items = [{**self._pack_public(pack), "progress": self._progress(pack, index, include_items=False)} for pack in packs]
        return {
            "policyVersion": CURRICULUM_POLICY_VERSION,
            "denominatorPolicyVersion": DENOMINATOR_POLICY_VERSION,
            "progressPolicyVersion": PROGRESS_POLICY_VERSION,
            "packs": items,
            "unavailablePacks": deepcopy((self._catalog or {}).get("unavailablePacks") or []),
            "boundaries": {
                "topics": "User Topics remain mutable partial groups; curricula are fixed reviewed versions.",
                "phrasebook": "Saved expressions are not curriculum membership or mastery.",
                "anki": "Curricula provide scope and navigation; Anki remains the only SRS.",
                "proficiency": "Pack progress is not CEFR or a universal Norway-readiness score.",
            },
        }

    def detail(self, profile_id: str, pack_id: str, version: int | str | None = None) -> dict[str, Any]:
        pack = self.pack(pack_id, version)
        index = self._knowledge_index(profile_id, [pack])
        return {**self._pack_public(pack), "progress": self._progress(pack, index, include_items=True)}

    def item_detail(self, profile_id: str, pack_id: str, version: int | str, membership_id: str) -> dict[str, Any]:
        pack = self.pack(pack_id, version)
        item = next((row for row in pack["items"] if row["membershipId"] == membership_id), None)
        if item is None:
            raise LanguageNotFoundError("Curriculum item was not found", code="curriculum_item_not_found")
        index = self._knowledge_index(profile_id, [pack])
        user = self._user_for_item(item, index)
        reference = {"reference": {"available": False}, "resolution": {"status": "UNAVAILABLE", "candidates": []}}
        lexical = {"dictionary": {"available": False, "lookupStatus": "NOT_LOADED", "articles": []}, "translations": {"user": [], "learnerGlosses": [], "polish": {"available": False, "status": "NOT_CONFIGURED"}}}
        if item["mappingState"] == "MAPPED" and self.reference_service is not None:
            from .reference_core.models import VocabularyLemmaIdentity
            unit = item["referenceUnit"]
            identity = VocabularyLemmaIdentity("nb", unit["normalizedForm"], unit.get("partOfSpeech"), user.get("userLemmaId"))
            try:
                reference = self.reference_service.get_reference_profile(identity)
                lexical["translations"]["learnerGlosses"] = self.reference_service.get_learner_glosses(
                    language_code="nb", lemma_normalized=unit["normalizedForm"],
                    part_of_speech=unit.get("partOfSpeech"), user_lemma_id=user.get("userLemmaId"),
                )
            except Exception:
                pass
            if self.dictionary_provider is not None:
                try:
                    lexical["dictionary"] = self.dictionary_provider.lookup_lemma(unit["canonicalForm"], unit.get("partOfSpeech"))
                except Exception as exc:
                    lexical["dictionary"] = {"available": False, "lookupStatus": "PROVIDER_UNAVAILABLE", "reason": str(exc), "articles": []}
        return {"pack": self._pack_public(pack), "item": {**deepcopy(item), "user": user}, **reference, "lexical": lexical}

    def collection_summaries(self, profile_id: str) -> list[dict[str, Any]]:
        packs = self.active_packs()
        index = self._knowledge_index(profile_id, packs)
        result = []
        for pack in packs:
            progress = self._progress(pack, index, include_items=False)
            meta = pack["pack"]
            result.append({
                "collectionKey": f"CURRICULUM:{meta['id']}:v{meta['version']}",
                "name": meta["name"], "kind": "CURRICULUM_PACK", "status": "AVAILABLE",
                "collectionVersion": CURRICULUM_POLICY_VERSION,
                "packId": meta["id"], "packVersion": meta["version"], "packFingerprint": meta["fingerprint"],
                "denominatorSource": f"{pack['source']['name']} · {pack['source']['version']}",
                "denominatorVersion": DENOMINATOR_POLICY_VERSION,
                "sourceTotal": progress["sourceItemTotal"], "approvedTotal": progress["approvedTotal"],
                "totalEligible": progress["eligibleDenominator"], "mapped": progress["mappedTotal"],
                "ambiguous": progress["ambiguousTotal"], "unresolved": progress["unresolvedTotal"],
                "excluded": progress["excludedTotal"], "completed": progress["completed"],
                "progressPercent": progress["progressPercent"], "stateCounts": progress["stateCounts"],
                "completionStateRule": progress["completionSemantics"],
                "completionRuleVersion": PROGRESS_POLICY_VERSION,
            })
        return result

    def collection_summary(self, profile_id: str, pack_id: str, version: int | str) -> dict[str, Any]:
        pack = self.pack(pack_id, version)
        index = self._knowledge_index(profile_id, [pack])
        progress = self._progress(pack, index, include_items=False)
        return {"pack": self._pack_public(pack), "progress": progress}

    def health(self) -> dict[str, Any]:
        packs = self.active_packs()
        current_reference = self.reference_service.health() if self.reference_service is not None else {"available": False}
        fingerprints = sorted({pack["mappingSnapshot"]["referenceFingerprint"] for pack in packs})
        return {
            "available": bool(packs), "policyVersion": CURRICULUM_POLICY_VERSION,
            "packCount": len(self._packs or {}), "activePackCount": len(packs),
            "mappingPolicyVersion": MAPPING_POLICY_VERSION,
            "mappingReferenceFingerprints": fingerprints,
            "currentReferenceFingerprint": current_reference.get("referenceFingerprint"),
            "currentReferenceMatches": bool(current_reference.get("referenceFingerprint") in fingerprints),
            "sourceSnapshots": [
                {"sourceId": source_id, "version": version}
                for source_id, version in sorted(
                    {(pack["source"]["id"], pack["source"]["version"]) for pack in packs}
                )
            ],
        }


__all__ = [
    "CURRICULUM_POLICY_VERSION", "DENOMINATOR_POLICY_VERSION", "MAPPING_POLICY_VERSION",
    "MANIFEST_VERSION", "PROGRESS_POLICY_VERSION", "CurriculumService",
    "curriculum_fingerprint", "validate_curriculum_manifest",
]
