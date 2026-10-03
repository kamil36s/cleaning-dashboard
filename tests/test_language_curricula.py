import copy
import json
from pathlib import Path
import tempfile
import unittest

from language_learning.curricula import (
    CurriculumService,
    curriculum_fingerprint,
    validate_curriculum_manifest,
)
from language_learning.errors import LanguageValidationError
from language_learning.service import LanguageService
from language_learning.store import LanguageStore


PACK_DIR = Path(__file__).resolve().parents[1] / "language_learning" / "curriculum_packs"


class LanguageCurriculumTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LanguageStore(Path(self.temp.name) / "language.sqlite")
        self.service = LanguageService(self.store)
        self.service.initialize()
        self.profile = self.service.ensure_bokmal_profile()["profile"]

    def tearDown(self):
        self.temp.cleanup()

    def _pack(self, name="nb.public-services.tax-v1.json"):
        return json.loads((PACK_DIR / name).read_text(encoding="utf-8"))

    def _table_counts(self):
        with self.store.connection() as connection:
            return tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
                "vocabulary_lemmas", "lemma_knowledge", "knowledge_events"
            ))

    def test_all_tracked_manifests_validate_with_transparent_counts(self):
        reports = []
        for path in PACK_DIR.glob("nb.*.json"):
            manifest = validate_curriculum_manifest(json.loads(path.read_text(encoding="utf-8")))
            counts = manifest["pack"]["denominatorCounts"]
            self.assertEqual(
                counts["sourceItemTotal"],
                counts["mappedTotal"] + counts["ambiguousTotal"]
                + counts["unresolvedTotal"] + counts["excludedTotal"],
            )
            self.assertEqual(counts["eligibleDenominator"], counts["mappedTotal"])
            reports.append(manifest)
        self.assertEqual(len(reports), 5)
        terms = [item for pack in reports for item in pack["items"]]
        self.assertTrue(any(" " in item["displayTerm"] for item in terms))
        self.assertTrue(any(any(ord(char) > 127 for char in item["displayTerm"]) for item in terms))

    def test_browsing_does_not_materialize_user_rows_and_unseen_is_distinct_from_new(self):
        before = self._table_counts()
        detail = self.service.curriculum_pack(
            self.profile["id"], "nb.public-services.tax", 1
        )["data"]
        self.assertEqual(before, self._table_counts())
        mapped = next(item for item in detail["progress"]["items"] if item["mappingState"] == "MAPPED")
        self.assertEqual(mapped["user"]["state"], "UNSEEN")
        unit = mapped["referenceUnit"]
        lemma = self.service.upsert_lemma(
            self.profile["id"], unit["canonicalForm"], part_of_speech=unit["partOfSpeech"]
        )["lemma"]
        refreshed = self.service.curriculum_pack(
            self.profile["id"], "nb.public-services.tax", 1
        )["data"]
        row = next(item for item in refreshed["progress"]["items"] if item["membershipId"] == mapped["membershipId"])
        self.assertEqual(row["user"]["state"], "NEW")
        self.assertFalse(row["user"]["acquired"])
        for state, acquired in (("LEARNING", False), ("KNOWN", True), ("MASTERED", True)):
            self.service.update_knowledge(lemma["id"], {"knowledgeStatus": state})
            current = self.service.curriculum_pack(
                self.profile["id"], "nb.public-services.tax", 1
            )["data"]
            row = next(item for item in current["progress"]["items"] if item["membershipId"] == mapped["membershipId"])
            self.assertEqual(row["user"]["state"], state)
            self.assertEqual(row["user"]["acquired"], acquired)

    def test_malformed_duplicate_and_changed_content_are_detected(self):
        manifest = self._pack()
        duplicate = copy.deepcopy(manifest["items"][0])
        manifest["items"].append(duplicate)
        manifest["pack"]["fingerprint"] = curriculum_fingerprint(manifest)
        with self.assertRaises(LanguageValidationError):
            validate_curriculum_manifest(manifest)

        changed = self._pack()
        original = changed["pack"]["fingerprint"]
        changed["items"][0]["displayTerm"] += " changed"
        changed["items"][0]["normalizedLookup"] += " changed"
        self.assertNotEqual(original, curriculum_fingerprint(changed))
        with self.assertRaises(LanguageValidationError):
            validate_curriculum_manifest(changed)

    def test_versions_remain_addressable_when_a_new_active_version_exists(self):
        directory = Path(self.temp.name) / "packs"
        directory.mkdir()
        v1 = self._pack()
        v1["pack"].update({"id": "nb.test-versioned", "slug": "test-versioned", "status": "ARCHIVED"})
        v1["pack"]["fingerprint"] = curriculum_fingerprint(v1)
        v2 = copy.deepcopy(v1)
        v2["pack"].update({"version": 2, "status": "ACTIVE"})
        v2["items"] = v2["items"][:-1]
        v2["pack"]["fingerprint"] = curriculum_fingerprint(v2)
        (directory / "v1.json").write_text(json.dumps(v1), encoding="utf-8")
        (directory / "v2.json").write_text(json.dumps(v2), encoding="utf-8")
        curricula = CurriculumService(self.store, manifest_directory=directory)
        self.assertEqual(curricula.pack("nb.test-versioned")["pack"]["version"], 2)
        self.assertEqual(curricula.pack("nb.test-versioned", 1)["pack"]["status"], "ARCHIVED")
        self.assertNotEqual(
            curricula.pack("nb.test-versioned", 1)["pack"]["fingerprint"],
            curricula.pack("nb.test-versioned", 2)["pack"]["fingerprint"],
        )

    def test_campaign_pins_pack_version_and_uses_curriculum_percentage(self):
        campaign = self.service.create_campaign(self.profile["id"], {
            "name": "Tax services",
            "targetDate": "2027-05-01",
            "milestones": [{
                "type": "CURRICULUM_PACK_PROGRESS", "packId": "nb.public-services.tax",
                "packVersion": 1, "target": 20,
            }],
        })["data"]["campaign"]
        milestone = campaign["milestones"][0]
        self.assertEqual(milestone["packVersion"], 1)
        self.assertTrue(milestone["packFingerprint"].startswith("sha256:"))
        self.assertEqual(milestone["current"], 0)
        pack = self.service.curriculum_pack(
            self.profile["id"], "nb.public-services.tax", 1
        )["data"]
        item = next(item for item in pack["progress"]["items"] if item["mappingState"] == "MAPPED")
        lemma = self.service.upsert_lemma(
            self.profile["id"], item["referenceUnit"]["canonicalForm"],
            part_of_speech=item["referenceUnit"]["partOfSpeech"],
        )["lemma"]
        self.service.update_knowledge(lemma["id"], {"knowledgeStatus": "KNOWN"})
        refreshed = self.service.campaigns(self.profile["id"])["data"]["items"][0]["milestones"][0]
        self.assertEqual(refreshed["current"], 20.0)
        self.assertTrue(refreshed["completed"])


if __name__ == "__main__":
    unittest.main()
