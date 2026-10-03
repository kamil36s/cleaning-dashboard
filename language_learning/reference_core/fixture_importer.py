"""Deterministic importer for tiny committed synthetic fixtures only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import ReferenceSourceRecord
from .store import ReferenceStore


FIXTURE_IMPORTER_ID = "reference-fixture-json"
FIXTURE_IMPORTER_VERSION = "1.0.0"


def import_fixture(store: ReferenceStore, fixture_path: str | Path) -> dict[str, Any]:
    path = Path(fixture_path)
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("formatVersion") != "language-reference-fixture/v1":
        raise ValueError("unsupported reference fixture version")
    checksum = "sha256:" + hashlib.sha256(raw).hexdigest()
    store.initialize()
    runs: dict[str, str] = {}
    accepted: dict[str, int] = {}
    for item in payload["sources"]:
        source = ReferenceSourceRecord(
            source_id=item["sourceId"], canonical_name=item["canonicalName"], provider=item["provider"],
            resource_type=item["resourceType"], language_code=item["languageCode"], version=item["version"],
            landing_url=item["landingUrl"], license_id=item.get("licenseId"),
            license_url=item.get("licenseUrl"), attribution_text=item.get("attributionText"),
        )
        store.register_source(source, format="synthetic-json", notes="Tiny synthetic test fixture")
        runs[source.source_id] = store.begin_import_run(
            source.source_id, importer_id=FIXTURE_IMPORTER_ID,
            importer_version=FIXTURE_IMPORTER_VERSION, source_checksum=checksum,
        )
        accepted[source.source_id] = 0
    units: dict[str, Any] = {}
    for item in payload["lexicalUnits"]:
        unit = store.upsert_lexical_unit(
            language_code=item["languageCode"], unit_type=item["unitType"],
            canonical_form=item["canonicalForm"], part_of_speech=item.get("partOfSpeech"),
            subtype=item.get("subtype"), identity_qualifier=item.get("identityQualifier"),
        )
        units[item["fixtureId"]] = unit
        source_id = item["sourceId"]
        store.link_source(
            unit.id, source_id=source_id, source_local_id=item["sourceLocalId"],
            import_run_id=runs[source_id], source_entry=item,
        )
        accepted[source_id] += 1
        for form in item.get("forms", []):
            store.link_form(
                unit.id, source_id=source_id, display_form=form["displayForm"],
                import_run_id=runs[source_id], form_type=form.get("formType"),
                orthographic_status=form.get("orthographicStatus"), morphology=form.get("morphology"),
            )
        if item.get("components"):
            store.add_mwe_components(unit.id, item["components"])
    for item in payload.get("frequency", []):
        unit = units[item["fixtureUnitId"]]
        values = {key: value for key, value in item.items() if key in {
            "raw_count", "rank", "frequency_per_million", "zipf_score", "document_frequency",
            "dispersion", "corpus_token_count", "genre", "period_start", "period_end", "method",
            "method_version", "raw_evidence",
        }}
        store.add_frequency(
            unit.id, source_id=item["sourceId"], metric_type=item["metricType"],
            observation_key=item["observationKey"], evidence_kind=item.get("evidenceKind", "RAW_SOURCE"),
            import_run_id=runs[item["sourceId"]], **values,
        )
    for item in payload.get("cefr", []):
        unit = units[item["fixtureUnitId"]]
        store.add_cefr(
            unit.id, source_id=item["sourceId"], evidence_type=item["evidenceType"],
            confidence=item["confidence"], best_level=item.get("bestLevel"),
            import_run_id=runs[item["sourceId"]], distribution=item.get("distribution"),
            method=item.get("method"), method_version=item.get("methodVersion"),
            raw_evidence=item.get("rawEvidence"),
        )
    for item in payload.get("associations", []):
        store.add_association(
            units[item["fixtureUnitId"]].id, source_id=item["sourceId"],
            relation_type=item["relationType"], metric_name=item["metricName"],
            metric_version=item["metricVersion"], metric_value=item["metricValue"],
            related_lexical_unit_id=units[item["relatedFixtureUnitId"]].id,
            raw_count=item.get("rawCount"), context=item.get("context"),
            import_run_id=runs[item["sourceId"]],
        )
    for source_id, run_id in runs.items():
        store.complete_import_run(
            run_id, rows_read=accepted[source_id], rows_accepted=accepted[source_id]
        )
    return {"checksum": checksum, "sources": len(runs), "lexicalUnits": len(units)}


__all__ = ["FIXTURE_IMPORTER_ID", "FIXTURE_IMPORTER_VERSION", "import_fixture"]
