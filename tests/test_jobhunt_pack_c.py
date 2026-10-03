import sqlite3
import tempfile
import unittest
from pathlib import Path

from jobhunt_backend import JobhuntError, JobhuntService
from jobhunt_backend.migrations import (
    MIGRATION_1_SQL,
    MIGRATION_2_SQL,
    MIGRATION_3_SQL,
    MIGRATIONS,
    SCHEMA_VERSION,
)


def seed_pack_b_database(path: Path) -> None:
    now = "2026-09-18T10:00:00+00:00"
    with sqlite3.connect(path) as connection:
        connection.executescript(MIGRATION_1_SQL)
        connection.executescript(MIGRATION_2_SQL)
        connection.executescript(MIGRATION_3_SQL)
        connection.execute(
            "CREATE TABLE jobhunt_schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL,backup_path TEXT)"
        )
        connection.executemany(
            "INSERT INTO jobhunt_schema_migrations(version,applied_at,checksum,backup_path) VALUES(?,?,?,NULL)",
            [(item.version, now, item.checksum) for item in MIGRATIONS[:3]],
        )
        connection.execute(
            """INSERT INTO career_profile(
                   id,current_role_title,headline,professional_summary,revision,fingerprint,created_at,updated_at
               ) VALUES('default','QA Analyst','Pack B profile',NULL,0,'sha256:pack-b',?,?)""",
            (now, now),
        )
        connection.execute(
            "INSERT INTO career_profile_revisions(revision,fingerprint,snapshot_json,changed_at) VALUES(0,'sha256:pack-b','{}',?)",
            (now,),
        )


def job_payload(company="ACME"):
    return {
        "company": company,
        "role": "QA Analyst",
        "location": {"city": "Kraków", "country": "Poland", "workMode": "hybrid"},
        "contract": {"type": "UoP"},
        "salary": {"isKnown": False},
        "source": {"name": "manual"},
        "status": "to_review",
        "priority": "P2",
        "nextAction": "analyze",
        "originalText": "Manual opportunity",
    }


class JobhuntPackCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = JobhuntService(
            self.root / "jobhunt.sqlite", private_root=self.root / "private"
        )
        self.service.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_pack_b_to_pack_c_migration_preserves_profile_and_checksums(self):
        database = self.root / "pack-b.sqlite"
        seed_pack_b_database(database)
        migrated = JobhuntService(database, private_root=self.root / "pack-b-private")
        migrated.initialize()
        self.assertEqual(migrated.store.schema_status()["version"], SCHEMA_VERSION)
        self.assertEqual(migrated.get_profile()["data"]["profile"]["headline"], "Pack B profile")
        with migrated.store.read_connection() as connection:
            ledger = connection.execute(
                "SELECT version,checksum FROM jobhunt_schema_migrations ORDER BY version"
            ).fetchall()
        self.assertEqual([row[0] for row in ledger], [item.version for item in MIGRATIONS])
        self.assertEqual([row[1] for row in ledger], [item.checksum for item in MIGRATIONS])

    def test_seed_tracks_and_profiles_are_idempotent_and_user_edits_survive(self):
        tracks = self.service.list_tracks()["data"]["tracks"]
        self.assertEqual(
            {track["name"]: track["status"] for track in tracks},
            {
                "QA Poland": "exploring",
                "Kraków Weekend Work": "exploring",
                "Norway Physical Work": "exploring",
                "Norway QA": "exploring",
                "Iceland Physical Work": "exploring",
            },
        )
        self.assertEqual(sum(track["searchProfileCount"] for track in tracks), 25)
        qa = next(track for track in tracks if track["slug"] == "qa-poland")
        self.service.update_track(qa["id"], {"name": "My QA route", "status": "active"})
        self.service.initialize()
        again = self.service.list_tracks()["data"]["tracks"]
        self.assertEqual(len(again), 5)
        edited = next(track for track in again if track["id"] == qa["id"])
        self.assertEqual((edited["name"], edited["status"]), ("My QA route", "active"))
        self.assertEqual(edited["searchProfileCount"], 4)

    def test_track_crud_lifecycle_slug_uniqueness_and_unknown_values(self):
        created = self.service.create_track({
            "name": "QA Abroad", "purpose": "Explore QA relocation", "status": "exploring",
            "geography": {"countries": ["NO"], "remoteAllowed": None, "relocationRelevant": True},
            "rationale": None,
        })["data"]["track"]
        self.assertEqual(created["slug"], "qa-abroad")
        self.assertIsNone(created["geography"]["remoteAllowed"])
        paused = self.service.update_track(created["id"], {"status": "paused"})["data"]["track"]
        self.assertEqual(paused["status"], "paused")
        archived = self.service.update_track(created["id"], {"status": "archived"})["data"]["track"]
        self.assertEqual(archived["status"], "archived")
        restored = self.service.update_track(created["id"], {"status": "active"})["data"]["track"]
        self.assertEqual(restored["status"], "active")
        with self.assertRaises(JobhuntError) as conflict:
            self.service.create_track({"name": "Duplicate", "slug": "qa-abroad"})
        self.assertEqual(conflict.exception.code, "track_slug_conflict")

    def test_search_profile_filters_sources_status_and_track_ownership(self):
        first, second = self.service.list_tracks()["data"]["tracks"][:2]
        profile = self.service.create_search_profile(first["id"], {
            "name": "Focused search", "includeKeywords": ["QA", "testing"],
            "excludeKeywords": ["manager"], "roleIntent": "Manual testing",
            "countries": ["PL"], "regionsCities": ["Kraków"],
            "workModels": ["hybrid"], "scheduleHints": ["weekday"],
            "contractHints": ["UoP"], "languageHints": ["English B2"],
            "seniorityHints": ["mid"], "plannedSourceKeys": ["pracuj", "company_sites"],
        })["data"]["searchProfile"]
        self.assertEqual(profile["includeKeywords"], ["QA", "testing"])
        self.assertEqual(profile["plannedSourceKeys"], ["pracuj", "company_sites"])
        paused = self.service.update_search_profile(profile["id"], {"status": "paused"})["data"]["searchProfile"]
        self.assertEqual(paused["status"], "paused")
        with self.assertRaises(JobhuntError) as mismatch:
            self.service.update_search_profile(profile["id"], {"trackId": second["id"]})
        self.assertEqual(mismatch.exception.code, "search_profile_track_mismatch")
        with self.assertRaises(JobhuntError) as source:
            self.service.update_search_profile(profile["id"], {"plannedSourceKeys": ["live-scraper"]})
        self.assertEqual(source.exception.code, "invalid_source_hint")

    def test_many_to_many_assignments_are_idempotent_and_domain_separated(self):
        job_id = self.service.create_job(job_payload())["data"]["job"]["id"]
        tracks = self.service.list_tracks()["data"]["tracks"]
        selected = [tracks[0]["id"], tracks[1]["id"]]
        job_before = self.service.get_job(job_id)["data"]["job"]
        profile_before = self.service.get_profile()["data"]["profile"]
        self.service.set_job_tracks(job_id, {"trackIds": selected, "note": "Relevant for review"})
        self.service.set_job_tracks(job_id, {"trackIds": selected, "note": "Relevant for review"})
        assigned = self.service.get_job_tracks(job_id)["data"]["tracks"]
        self.assertEqual({item["trackId"] for item in assigned if item["assigned"]}, set(selected))
        with self.service.store.read_connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM track_job_assignments WHERE job_id=?", (job_id,)
            ).fetchone()[0], 2)
        detail = self.service.get_track(selected[0])["data"]
        self.assertEqual(detail["assignedJobs"][0]["jobId"], job_id)
        self.service.update_track(selected[0], {"status": "paused"})
        self.assertEqual(len(self.service.get_track(selected[0])["data"]["assignedJobs"]), 1)
        self.service.set_job_tracks(job_id, {"trackIds": [selected[1]]})
        removed = self.service.get_job_tracks(job_id)["data"]["tracks"]
        self.assertFalse(next(item for item in removed if item["trackId"] == selected[0])["assigned"])
        job_after = self.service.get_job(job_id)["data"]["job"]
        profile_after = self.service.get_profile()["data"]["profile"]
        self.assertEqual(job_after["applicationStatus"], job_before["applicationStatus"])
        self.assertEqual(job_after["company"], job_before["company"])
        self.assertEqual(profile_after["fingerprint"], profile_before["fingerprint"])

    def test_archived_track_keeps_history_and_rejects_new_assignment(self):
        job_id = self.service.create_job(job_payload("Archived Test"))["data"]["job"]["id"]
        track = self.service.list_tracks()["data"]["tracks"][0]
        self.service.update_track(track["id"], {"status": "archived"})
        with self.assertRaises(JobhuntError) as archived:
            self.service.set_job_tracks(job_id, {"trackIds": [track["id"]]})
        self.assertEqual(archived.exception.code, "track_archived")


if __name__ == "__main__":
    unittest.main()
