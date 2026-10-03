"""Build reviewed Los curriculum manifests from a pinned RDF snapshot.

The command is intentionally offline: callers download and checksum the source
artifact first, then supply it explicitly. Only recursive leaf concepts are pack
members; grouping concepts are never silently presented as vocabulary items.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from language_learning.analysis.base import normalize_lookup  # noqa: E402
from language_learning.curricula import (  # noqa: E402
    CURRICULUM_POLICY_VERSION,
    DENOMINATOR_POLICY_VERSION,
    MANIFEST_VERSION,
    MAPPING_POLICY_VERSION,
    PROGRESS_POLICY_VERSION,
    curriculum_fingerprint,
    validate_curriculum_manifest,
)
from language_learning.reference_core.service import ReferenceLexiconService  # noqa: E402


RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
SKOS = "{http://www.w3.org/2004/02/skos/core#}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
LOS_SOURCE_SHA256 = "e6f3266e404aa91d73e31cec0f211814f2fe9a6daadbc1864478287239ba837f"
LOS_SOURCE_VERSION = "3.0-rdf-2023-03-01"
RELEASE_DATE = "2026-09-17"
PACKS = (
    ("nb.public-services.work", "Work and employment services", "WORK", "arbeid", 10),
    ("nb.public-services.housing", "Housing and property services", "HOUSING", "bygg-og-eiendom", 20),
    ("nb.public-services.healthcare", "Health and care services", "HEALTHCARE", "helse-og-omsorg", 30),
    ("nb.public-services.transport", "Traffic and transport services", "TRANSPORT", "trafikk-og-transport", 40),
    ("nb.public-services.tax", "Tax and duties services", "TAX", "skatt-og-avgift", 50),
)


def _concepts(source_path: Path) -> dict[str, dict[str, object]]:
    root = ET.parse(source_path).getroot()
    result: dict[str, dict[str, object]] = {}
    for node in root.findall(f"{RDF}Description"):
        uri = node.get(f"{RDF}about")
        if not uri:
            continue
        label = next(
            (item.text for item in node.findall(f"{SKOS}prefLabel") if item.get(XML_LANG) == "nb" and item.text),
            None,
        )
        children = [item.get(f"{RDF}resource") for item in node.findall(f"{SKOS}narrower")]
        result[uri] = {"label": label, "children": [item for item in children if item]}
    return result


def _leaf_members(concepts: dict[str, dict[str, object]], root_uri: str) -> list[tuple[str, str]]:
    leaves: dict[str, str] = {}
    visiting: set[str] = set()

    def walk(uri: str) -> None:
        if uri in visiting:
            raise ValueError(f"Los hierarchy cycle at {uri}")
        visiting.add(uri)
        concept = concepts.get(uri)
        if not concept:
            raise ValueError(f"Los hierarchy references missing concept {uri}")
        children = list(concept["children"])
        if children:
            for child in children:
                walk(str(child))
        else:
            label = concept.get("label")
            if label:
                leaves[uri] = str(label)
        visiting.remove(uri)

    walk(root_uri)
    return sorted(leaves.items(), key=lambda value: (normalize_lookup(value[1]), value[0]))


def _unit(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"], "stableKey": row["stable_key"],
        "canonicalForm": row["canonical_form"], "normalizedForm": row["normalized_form"],
        "partOfSpeech": row["part_of_speech"], "unitType": row["unit_type"],
    }


def build(source_path: Path, reference_db: Path, output: Path) -> list[Path]:
    checksum = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if checksum != LOS_SOURCE_SHA256:
        raise ValueError(f"Unexpected Los snapshot SHA-256: {checksum}")
    reference = ReferenceLexiconService(reference_db)
    reference_health = reference.health()
    if not reference_health.get("available"):
        raise ValueError(f"Reference database is unavailable: {reference_health.get('reason')}")
    concepts = _concepts(source_path)
    connection = sqlite3.connect(reference_db.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        for pack_id, name, category, slug, order in PACKS:
            members = _leaf_members(concepts, f"https://psi.norge.no/los/tema/{slug}")
            items = []
            for source_uri, label in members:
                normalized = normalize_lookup(label)
                rows = connection.execute(
                    "SELECT id,stable_key,canonical_form,normalized_form,part_of_speech,unit_type "
                    "FROM reference_lexical_units WHERE language_code='nb' AND normalized_form=? "
                    "AND unit_type IN ('LEMMA','PHRASE','IDIOM','COLLOCATION','FORMULA') ORDER BY id",
                    (normalized,),
                ).fetchall()
                mapping = "MAPPED" if len(rows) == 1 else "AMBIGUOUS" if rows else "UNRESOLVED"
                membership_id = hashlib.sha256(f"{pack_id}|1|{source_uri}".encode()).hexdigest()[:32]
                item = {
                    "membershipId": membership_id, "sourceMembershipId": source_uri,
                    "displayTerm": label, "normalizedLookup": normalized,
                    "reviewState": "APPROVED", "mappingState": mapping,
                    "mappingBasis": (
                        "REFERENCE_RESOLVER_UNIQUE_NULL_POS_SNAPSHOT" if mapping == "MAPPED" else
                        "REFERENCE_RESOLVER_POS_REQUIRED_SNAPSHOT" if mapping == "AMBIGUOUS" else
                        "NO_EXACT_REFERENCE_CANDIDATE"
                    ),
                    "priority": "USEFUL", "weight": 1.0,
                    "provenanceClass": "SOURCE_MEMBERSHIP",
                }
                if mapping == "MAPPED":
                    item["referenceUnit"] = _unit(rows[0])
                elif mapping == "AMBIGUOUS":
                    item["mappingCandidates"] = [_unit(row) for row in rows]
                items.append(item)
            manifest = {
                "schemaVersion": MANIFEST_VERSION,
                "pack": {
                    "id": pack_id, "version": 1, "slug": slug, "language": "nb",
                    "name": name,
                    "description": f"Official public-service concepts under the Los {name.lower()} theme.",
                    "category": category, "sourceType": "OFFICIAL_SOURCE",
                    "reviewState": "SOURCE_APPROVED", "status": "ACTIVE", "displayOrder": order,
                    "releasedDate": RELEASE_DATE,
                    "curriculumPolicyVersion": CURRICULUM_POLICY_VERSION,
                    "denominatorPolicyVersion": DENOMINATOR_POLICY_VERSION,
                    "progressPolicyVersion": PROGRESS_POLICY_VERSION,
                },
                "source": {
                    "id": "digdir-los-3.0-2023-03-01", "provider": "Digitaliseringsdirektoratet (Digdir)",
                    "name": "Los – common terminology for public services", "version": LOS_SOURCE_VERSION,
                    "url": "https://data.norge.no/en/datasets/c479c6db-af9d-4467-a238-f30480d153e9/los-felles-terminologi-for-offentlige-tjenester",
                    "license": "CC0-1.0", "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
                    "attribution": "Digitaliseringsdirektoratet, Los 3.0 (CC0).",
                    "membershipBasis": f"Recursive leaf SKOS concepts below https://psi.norge.no/los/tema/{slug}; grouping concepts excluded.",
                },
                "mappingSnapshot": {
                    "mappingPolicyVersion": MAPPING_POLICY_VERSION,
                    "resolverRuleVersion": "reference-resolver/exact-normalized-null-pos/v1",
                    "referenceSchemaVersion": reference_health["schemaVersion"],
                    "referenceFingerprint": reference_health["referenceFingerprint"],
                    "sourceArtifactSha256": f"sha256:{checksum}",
                    "sourceArtifactLastModified": "2023-03-01T13:09:58Z",
                    "mappedDate": RELEASE_DATE,
                },
                "items": items,
            }
            manifest["pack"]["fingerprint"] = curriculum_fingerprint(manifest)
            validate_curriculum_manifest(manifest)
            target = output / f"{pack_id}-v1.json"
            target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written.append(target)
    finally:
        connection.close()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Pinned Los all.rdf snapshot")
    parser.add_argument("--reference-db", type=Path, default=ROOT / "data/reference/language-reference-nb.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "language_learning/curriculum_packs")
    args = parser.parse_args()
    for path in build(args.source, args.reference_db, args.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
