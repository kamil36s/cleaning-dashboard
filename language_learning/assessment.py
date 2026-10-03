"""Fixed, server-scored receptive benchmarks; no learning evidence is written here."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unicodedata
from typing import Any

from .errors import LanguageConflictError, LanguageNotFoundError, LanguageValidationError
from .store import LanguageStore, canonical_json, new_id, utc_now

DIMENSIONS = ("VOCABULARY", "CLOZE", "READING", "LISTENING")
CONTENT_PATH = Path(__file__).with_name("benchmark_content") / "v1.json"


def load_content() -> tuple[dict[str, Any], str]:
    content = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    if content.get("status") != "INTERNAL_SYNTHETIC" or content.get("version") != 1:
        raise ValueError("Unsupported benchmark content")
    ids = set()
    blueprint = None
    for items in content["forms"].values():
        counts = {dimension: 0 for dimension in DIMENSIONS}
        for item in items:
            if item["id"] in ids or item["dimension"] not in counts or item.get("itemVersion") != 1:
                raise ValueError("Invalid benchmark item identity")
            ids.add(item["id"])
            counts[item["dimension"]] += 1
            if item["dimension"] != "CLOZE" and item["answer"] not in item["options"]:
                raise ValueError("Invalid benchmark answer")
        if blueprint is not None and counts != blueprint:
            raise ValueError("Benchmark form blueprints differ")
        blueprint = counts
    fingerprint = hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()
    return content, fingerprint


def normalize_cloze(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip()).casefold()


class AssessmentService:
    def __init__(self, store: LanguageStore, curriculum_service: Any):
        self.store = store
        self.curriculum_service = curriculum_service
        self.content, self.fingerprint = load_content()

    def _profile(self, connection, profile_id: str) -> None:
        if not connection.execute("SELECT 1 FROM language_profiles WHERE id=?", (profile_id,)).fetchone():
            raise LanguageNotFoundError("Language profile was not found")

    def _run(self, connection, profile_id: str, run_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM benchmark_runs WHERE id=? AND language_profile_id=?", (run_id, profile_id)
        ).fetchone()
        if not row:
            raise LanguageNotFoundError("Benchmark run was not found")
        return dict(row)

    def _items(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        if run["content_fingerprint"] != self.fingerprint or run["benchmark_version"] != self.content["version"]:
            raise LanguageConflictError("Benchmark content changed; this run cannot continue", code="benchmark_content_changed")
        raw_items = self.content["forms"].get(run["form_id"])
        items = sorted(raw_items, key=lambda item: DIMENSIONS.index(item["dimension"])) if raw_items else None
        if items is None or [item["id"] for item in items] != json.loads(run["selected_item_ids_json"]):
            raise LanguageConflictError("Benchmark form changed", code="benchmark_content_changed")
        return items

    @staticmethod
    def _public_item(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key != "answer"}

    def _public_run(self, connection, run: dict[str, Any], response_rows=None, *, include_items=True) -> dict[str, Any]:
        if response_rows is None:
            response_rows = connection.execute("SELECT * FROM benchmark_responses WHERE run_id=?", (run["id"],))
        responses = {
            row["item_id"]: {"response": json.loads(row["response_json"]),
                             "environment": json.loads(row["environment_json"]) if row["environment_json"] else None,
                             "answeredAt": row["answered_at"]}
            for row in response_rows
        }
        result = {
            "id": run["id"], "profileId": run["language_profile_id"], "kind": run["kind"],
            "status": run["status"], "benchmarkFamilyId": run["benchmark_family_id"],
            "benchmarkVersion": run["benchmark_version"], "formId": run["form_id"],
            "contentFingerprint": run["content_fingerprint"], "scoringVersion": run["scoring_version"],
            "selectedItemIds": json.loads(run["selected_item_ids_json"]),
            "startedAt": run["started_at"], "completedAt": run["completed_at"],
            "responses": responses, "scores": json.loads(run["scores_json"]) if run["scores_json"] else None,
            "comparison": json.loads(run["comparison_json"]) if run["comparison_json"] else None,
        }
        if run["status"] == "ACTIVE" and include_items:
            result["items"] = [self._public_item(item) for item in self._items(run)]
        return result

    def list_runs(self, profile_id: str) -> dict[str, Any]:
        with self.store.connection() as connection:
            self._profile(connection, profile_id)
            rows = connection.execute(
                "SELECT * FROM benchmark_runs WHERE language_profile_id=? ORDER BY started_at DESC,id DESC LIMIT 100",
                (profile_id,),
            ).fetchall()
            grouped = {row["id"]: [] for row in rows}
            if rows:
                placeholders = ",".join("?" for _ in rows)
                for response in connection.execute(
                    f"SELECT * FROM benchmark_responses WHERE run_id IN ({placeholders})", tuple(grouped)
                ):
                    grouped[response["run_id"]].append(response)
            return {"contentStatus": "INTERNAL_SYNTHETIC",
                    "runs": [self._public_run(connection, dict(row), grouped[row["id"]], include_items=False) for row in rows]}

    def start(self, profile_id: str) -> dict[str, Any]:
        with self.store.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._profile(connection, profile_id)
            active = connection.execute(
                "SELECT * FROM benchmark_runs WHERE language_profile_id=? AND status='ACTIVE' ORDER BY started_at LIMIT 1",
                (profile_id,),
            ).fetchone()
            if active:
                return self._public_run(connection, dict(active))
            previous = connection.execute(
                "SELECT COUNT(*) FROM benchmark_runs WHERE language_profile_id=? AND status='COMPLETED'",
                (profile_id,),
            ).fetchone()[0]
            form_id = "FORM_A" if previous % 2 == 0 else "FORM_B"
            items = sorted(self.content["forms"][form_id], key=lambda item: DIMENSIONS.index(item["dimension"]))
            earlier = connection.execute(
                "SELECT form_id,started_at,selected_item_ids_json FROM benchmark_runs "
                "WHERE language_profile_id=? ORDER BY started_at,id", (profile_id,)
            ).fetchall()
            first_seen = {}
            for old in earlier:
                for old_id in json.loads(old["selected_item_ids_json"]):
                    first_seen.setdefault(old_id, old["started_at"])
            repeated = {item["id"]: first_seen[item["id"]] for item in items if item["id"] in first_seen}
            initial_comparison = {"policyVersion": "benchmark-comparison/v1",
                                  "itemVersions": {item["id"]: item["itemVersion"] for item in items},
                                  "repeatInfluence": {"itemFirstSeenAt": repeated,
                                                      "repeatedItemCount": len(repeated)}}
            run_id = new_id()
            connection.execute(
                "INSERT INTO benchmark_runs(id,language_profile_id,kind,status,benchmark_family_id,benchmark_version,"
                "form_id,content_fingerprint,scoring_version,selected_item_ids_json,started_at,comparison_json) "
                "VALUES(?,?,?,'ACTIVE',?,?,?,?,?,?,?,?)",
                (run_id, profile_id, "BASELINE" if previous == 0 else "CHECKPOINT", self.content["familyId"],
                 self.content["version"], form_id, self.fingerprint, self.content["scoringVersion"],
                 canonical_json([item["id"] for item in items]), utc_now(), canonical_json(initial_comparison)),
            )
            return self._public_run(connection, self._run(connection, profile_id, run_id))

    def get(self, profile_id: str, run_id: str) -> dict[str, Any]:
        with self.store.connection() as connection:
            return self._public_run(connection, self._run(connection, profile_id, run_id))

    def respond(self, profile_id: str, run_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("itemId"), str):
            raise LanguageValidationError("itemId is required")
        with self.store.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._run(connection, profile_id, run_id)
            if run["status"] != "ACTIVE":
                raise LanguageConflictError("Benchmark is completed")
            item = next((item for item in self._items(run) if item["id"] == payload["itemId"]), None)
            if not item:
                raise LanguageValidationError("Benchmark item does not belong to this run")
            skipped = payload.get("unavailable") is True
            if skipped and item["dimension"] != "LISTENING":
                raise LanguageValidationError("Only unavailable Listening items may be skipped")
            value = payload.get("response")
            if not skipped and (not isinstance(value, str) or not value.strip() or len(value) > 200):
                raise LanguageValidationError("A bounded response is required")
            if not skipped and item["dimension"] != "CLOZE" and value not in item["options"]:
                raise LanguageValidationError("Response is not an offered option")
            environment = payload.get("environment")
            if environment is not None and (not isinstance(environment, dict) or len(canonical_json(environment)) > 1000):
                raise LanguageValidationError("Listening environment is invalid")
            if item["dimension"] != "LISTENING" and environment is not None:
                raise LanguageValidationError("Environment belongs to Listening only")
            existing = connection.execute(
                "SELECT 1 FROM benchmark_responses WHERE run_id=? AND item_id=?", (run_id, item["id"])
            ).fetchone()
            if existing:
                raise LanguageConflictError("Item already answered")
            connection.execute(
                "INSERT INTO benchmark_responses(run_id,item_id,dimension,response_json,environment_json,answered_at) "
                "VALUES(?,?,?,?,?,?)",
                (run_id, item["id"], item["dimension"], canonical_json({"unavailable": True} if skipped else value),
                 canonical_json(environment) if environment is not None else None, utc_now()),
            )
            return self._public_run(connection, run)

    def complete(self, profile_id: str, run_id: str) -> dict[str, Any]:
        with self.store.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._run(connection, profile_id, run_id)
            if run["status"] == "COMPLETED":
                return self._public_run(connection, run)
            items = self._items(run)
            answers = {
                row["item_id"]: json.loads(row["response_json"])
                for row in connection.execute("SELECT item_id,response_json FROM benchmark_responses WHERE run_id=?", (run_id,))
            }
            if set(answers) != {item["id"] for item in items}:
                raise LanguageConflictError("Answer every item or mark Listening unavailable")
            scores = {}
            for dimension in DIMENSIONS:
                section = [item for item in items if item["dimension"] == dimension]
                applicable = [item for item in section if answers[item["id"]] != {"unavailable": True}]
                correct = sum(
                    normalize_cloze(answers[item["id"]]) == normalize_cloze(item["answer"])
                    if dimension == "CLOZE" else answers[item["id"]] == item["answer"]
                    for item in applicable
                )
                scores[dimension] = {"correct": correct, "total": len(applicable),
                                     "unavailable": len(section) - len(applicable),
                                     "percent": round(100 * correct / len(applicable), 1) if applicable else None,
                                     "status": "PARTIAL" if applicable and len(applicable) < len(section)
                                     else "SCORED" if applicable else "UNAVAILABLE"}
            baseline = connection.execute(
                "SELECT * FROM benchmark_runs WHERE language_profile_id=? AND kind='BASELINE' AND status='COMPLETED' "
                "ORDER BY completed_at,id LIMIT 1", (profile_id,)
            ).fetchone()
            kind = "CHECKPOINT" if baseline else "BASELINE"
            comparison = {"policyVersion": "benchmark-comparison/v1", "state": "NO_BASELINE",
                          "itemVersions": json.loads(run["comparison_json"])["itemVersions"],
                          "repeatInfluence": json.loads(run["comparison_json"])["repeatInfluence"],
                          "baselineRunId": None, "dimensions": {}}
            if baseline:
                baseline = dict(baseline)
                same = (baseline["benchmark_version"] == run["benchmark_version"]
                        and baseline["scoring_version"] == run["scoring_version"]
                        and baseline["content_fingerprint"] == run["content_fingerprint"])
                repeat = same and baseline["form_id"] == run["form_id"]
                comparison["state"] = "REPEAT_INFLUENCED" if repeat else "NOT_COMPARABLE"
                comparison["baselineRunId"] = baseline["id"]
                baseline_scores = json.loads(baseline["scores_json"])
                comparison["dimensions"] = {
                    dimension: {
                        "state": comparison["state"],
                        "changePp": round(scores[dimension]["percent"] - baseline_scores[dimension]["percent"], 1)
                        if repeat and scores[dimension]["percent"] is not None
                        and baseline_scores[dimension]["percent"] is not None else None,
                    }
                    for dimension in DIMENSIONS
                }
            connection.execute(
                "UPDATE benchmark_runs SET kind=?,status='COMPLETED',completed_at=?,scores_json=?,comparison_json=? WHERE id=?",
                (kind, utc_now(), canonical_json(scores), canonical_json(comparison), run_id),
            )
            return self._public_run(connection, self._run(connection, profile_id, run_id))

    def norway_preparation(self, profile_id: str) -> dict[str, Any]:
        # CurriculumService uses a bulk knowledge snapshot; no benchmark answer is promoted into it.
        landing = self.curriculum_service.landing(profile_id)
        with self.store.connection() as connection:
            self._profile(connection, profile_id)
            latest = connection.execute(
                "SELECT scores_json,id FROM benchmark_runs WHERE language_profile_id=? AND status='COMPLETED' "
                "ORDER BY completed_at DESC,id DESC LIMIT 1", (profile_id,)
            ).fetchone()
        packs = [{"name": pack["name"], "packId": pack["id"], "version": pack["version"],
                  "completed": pack["progress"]["completed"],
                  "total": pack["progress"]["eligibleDenominator"], "source": pack["source"].get("name")}
                 for pack in landing["packs"]]
        scores = json.loads(latest["scores_json"]) if latest else {}
        return {"policyVersion": "norway-preparation/v1", "curricula": packs,
                "benchmarks": {dimension: scores.get(dimension) for dimension in ("READING", "LISTENING")},
                "benchmarkRunId": latest["id"] if latest else None}
