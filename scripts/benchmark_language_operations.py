"""Offline, generated personal-scale Language read benchmark; prints JSON only."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from language_learning.cloze import ClozeService  # noqa: E402
from language_learning.backup import create_backup, restore_backup, validate_backup  # noqa: E402
from language_learning.assessment import load_content  # noqa: E402
from language_learning.grammar_nb import CATALOGUE  # noqa: E402
from language_learning.service import LanguageService  # noqa: E402
from language_learning.store import LanguageStore  # noqa: E402


STAMP = "2026-09-24T12:00:00Z"


def fixture(store: LanguageStore, profile: str, *, lemmas: int, texts: int,
            events: int) -> dict:
    """Insert deterministic synthetic rows into a temporary v16 store."""
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        lemma_rows = []
        knowledge_rows = []
        for n in range(lemmas):
            identity = f"{n+1:032x}"
            word = f"ord{n:05d}"
            lemma_rows.append((identity, profile, word, word, "NOUN", f"nb|{word}|NOUN",
                               "MANUAL", STAMP, STAMP))
            knowledge_rows.append((identity, "KNOWN" if n % 4 == 0 else "LEARNING",
                                   STAMP))
        db.executemany("INSERT INTO vocabulary_lemmas(id,language_profile_id,lemma_display,"
                       "lemma_normalized,part_of_speech,canonical_key,source_kind,created_at,updated_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?)", lemma_rows)
        db.executemany("INSERT INTO lemma_knowledge(lemma_id,knowledge_status,updated_at) VALUES(?,?,?)",
                       knowledge_rows)
        db.executemany("INSERT INTO knowledge_events(id,lemma_id,event_type,source,created_at)"
                       " VALUES(?,?,?,?,?)", [
                           (f"{n+1:032x}", f"{n % lemmas + 1:032x}", "STATUS_CHANGED", "SYNTHETIC", STAMP)
                           for n in range(events)
                       ])
        text_rows = []
        sentence_rows = []
        token_rows = []
        progress_rows = []
        for n in range(texts):
            text_id = f"{100000+n:032x}"
            sentence_id = f"{200000+n:032x}"
            words = [f"ord{(n*20+j) % lemmas:05d}" for j in range(20)]
            raw = " ".join(words) + "."
            text_rows.append((text_id, profile, f"Synthetic Reader {n:04d}", raw,
                              "PASTED", f"synthetic-{n}", "ANALYZED", STAMP, STAMP))
            sentence_rows.append((sentence_id, text_id, 0, 0, len(raw),
                                  "UNICODE_CODE_POINT", raw, f"synthetic-{n}"))
            for j, word in enumerate(words):
                start = j * 9
                token_rows.append((f"{300000+n*20+j:032x}", profile, text_id, sentence_id,
                                   j, word, start, start + len(word), "UNICODE_CODE_POINT", "WORD",
                                   word, f"{(n*20+j) % lemmas + 1:032x}", "NOT_REPORTED",
                                   "NOT_ASSESSED", "MODEL_SELECTED"))
            progress_rows.append((text_id, profile, "IN_PROGRESS" if n % 2 else "COMPLETED",
                                  STAMP, STAMP, STAMP))
        db.executemany("INSERT INTO text_documents(id,language_profile_id,title,raw_text,source_type,"
                       "content_fingerprint,processing_state,created_at,updated_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?)", text_rows)
        db.executemany("INSERT INTO text_sentences(id,text_document_id,sentence_order,source_start,"
                       "source_end,offset_unit,exact_text,fingerprint) VALUES(?,?,?,?,?,?,?,?)", sentence_rows)
        db.executemany("INSERT INTO text_tokens(id,language_profile_id,text_document_id,sentence_id,"
                       "token_order,surface,source_start,source_end,offset_unit,token_kind,"
                       "normalized_lookup,selected_lemma_id,ambiguity_state,lexical_status,resolution_state)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", token_rows)
        db.executemany("INSERT INTO text_reading_progress(text_document_id,language_profile_id,status,"
                       "last_read_at,created_at,updated_at) VALUES(?,?,?,?,?,?)", progress_rows)
        reader_sessions = [(f"{600000+n:032x}", profile, f"{100000+n:032x}", "READER",
                            "COMPLETED", STAMP, STAMP, 180, STAMP, STAMP)
                           for n in range(texts)]
        listening_sessions = [(f"{700000+n:032x}", profile, f"{100000+n:032x}", "LISTENING",
                               "COMPLETED", STAMP, STAMP, 60, STAMP, STAMP)
                              for n in range(min(texts, 30))]
        db.executemany("INSERT INTO study_sessions(id,language_profile_id,text_document_id,"
                       "session_type,status,started_at,ended_at,active_seconds,created_at,updated_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?)", reader_sessions + listening_sessions)
        db.executemany("INSERT INTO exposure_events(id,idempotency_key,language_profile_id,lemma_id,"
                       "text_document_id,sentence_id,study_session_id,source_type,occurrence_count,"
                       "occurred_at,created_at,batch_idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", [
                           (f"{800000+n*10+j:032x}", f"synthetic-exposure-{n}-{j}", profile,
                            f"{(n*20+j) % lemmas + 1:032x}", f"{100000+n:032x}",
                            f"{200000+n:032x}", f"{600000+n:032x}", "READER", 1, STAMP, STAMP,
                            f"synthetic-batch-{n}")
                           for n in range(texts) for j in range(10)
                       ])
        db.executemany("INSERT INTO listening_sessions(study_session_id,language_profile_id,"
                       "text_document_id,mode,activity_policy_version,exposure_policy_version,"
                       "completion_policy_version,started_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", [
                           (f"{700000+n:032x}", profile, f"{100000+n:032x}", "READ_LISTEN",
                            "language.listening-activity/v1", "language.listening-exposure/v1",
                            "language.listening-completion/v1", STAMP, STAMP)
                           for n in range(min(texts, 30))
                       ])
        db.executemany("INSERT INTO listening_progress(language_profile_id,text_document_id,"
                       "current_sentence_id,status,policy_version,last_listened_at,updated_at)"
                       " VALUES(?,?,?,?,?,?,?)", [
                           (profile, f"{100000+n:032x}", f"{200000+n:032x}", "IN_PROGRESS",
                            "language.listening-progress/v1", STAMP, STAMP)
                           for n in range(min(texts, 30))
                       ])
        db.executemany("INSERT INTO listening_sentence_events(id,study_session_id,"
                       "language_profile_id,text_document_id,sentence_id,idempotency_key,outcome,"
                       "playback_source,active_ms,coverage_ms,duration_ms,completion_ratio,qualified,"
                       "exposure_awarded,local_study_date,occurred_at,created_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                           (f"{900000+n:032x}", f"{700000+n:032x}", profile,
                            f"{100000+n:032x}", f"{200000+n:032x}", f"listen-{n}",
                            "ENDED", "BROWSER_TTS", 2000, 2000, 2000, 1.0, 1, 0,
                            "2026-09-24", STAMP, STAMP)
                           for n in range(min(texts, 30))
                       ])
        pattern = next(item for item in CATALOGUE if item["status"] == "SUPPORTED")
        grammar_count = min(texts, 40)
        db.executemany("INSERT INTO analysis_runs(id,language_profile_id,text_document_id,"
                       "analyzer_id,analyzer_version,contract_version,state,content_fingerprint,created_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?)", [
                           (f"{1000000+n:032x}", profile, f"{100000+n:032x}", "synthetic", "1",
                            "language.analysis/v1", "COMPLETED", f"synthetic-{n}", STAMP)
                           for n in range(grammar_count)
                       ])
        db.executemany("INSERT INTO language_jobs(id,language_profile_id,text_document_id,job_type,"
                       "analyzer_id,analyzer_version,contract_version,analysis_policy_version,"
                       "frequency_provider_id,frequency_provider_version,coverage_policy_version,"
                       "content_fingerprint,analysis_fingerprint,state,stage,created_at,updated_at,analysis_domain)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                           (f"{1100000+n:032x}", profile, f"{100000+n:032x}", "ANALYZE",
                            "synthetic", "1", "language.analysis/v1", "synthetic/v1", "synthetic", "1",
                            "synthetic/v1", f"synthetic-{n}", f"grammar-{n}", "COMPLETED",
                            "COMPLETED", STAMP, STAMP, "GRAMMAR")
                           for n in range(grammar_count)
                       ])
        db.executemany("INSERT INTO grammar_analysis_runs(id,language_profile_id,text_document_id,"
                       "canonical_analysis_run_id,parser_provenance_json,analyzer_provenance_json,"
                       "source_provenance_json,registry_json,policy_version,created_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?)", [
                           (f"{1100000+n:032x}", profile, f"{100000+n:032x}",
                            f"{1000000+n:032x}", "{}", "{}", "{}", "{}",
                            "language.grammar-evidence/v1", STAMP)
                           for n in range(grammar_count)
                       ])
        db.executemany("INSERT INTO grammar_occurrences(id,run_id,language_profile_id,"
                       "text_document_id,sentence_id,pattern_id,pattern_version,detector_id,"
                       "detector_version,support_status,evidence_status,source_start,source_end,"
                       "evidence_json,semantic_key,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                           (f"{1200000+n:032x}", f"{1100000+n:032x}", profile,
                            f"{100000+n:032x}", f"{200000+n:032x}", pattern["patternId"],
                            pattern["patternVersion"], pattern["detectorId"],
                            pattern["detectorVersion"], "SUPPORTED", "SUPPORTED_RULE_MATCH",
                            0, 8, "{}", f"synthetic-grammar-{n}", STAMP)
                           for n in range(grammar_count)
                       ])
        db.executemany("INSERT INTO phrasebook_entries(id,language_profile_id,expression_text,"
                       "expression_normalized,source_type,source_fingerprint,created_at,updated_at)"
                       " VALUES(?,?,?,?,?,?,?,?)", [
                           (f"{400000+n:032x}", profile, f"synthetic expression {n}",
                            f"synthetic expression {n}", "MANUAL", f"{n+1:064x}", STAMP, STAMP)
                           for n in range(100)
                       ])
        db.executemany("INSERT INTO content_items(id,language_profile_id,content_type,title,source_type,"
                       "language_code,rights_status,retention_policy,rights_policy_version,"
                       "ingestion_policy_version,content_fingerprint,status,text_document_id,"
                       "created_at,added_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                           (f"{500000+n:032x}", profile, "PASTED_TEXT", f"Inbox {n}", "PASTED_TEXT",
                            "nb", "USER_PROVIDED_STORAGE_ALLOWED", "KEEP_UNTIL_USER_DELETES",
                            "language.content-rights/v1", "language.content-ingestion/v1",
                            f"content-{n}", "READY_READER", f"{100000+n:032x}", STAMP, STAMP, STAMP)
                           for n in range(min(texts, 50))
                       ])
        audio = b"RIFF" + (40).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 40
        audio_id = f"{1600000:032x}"
        content_id = f"{1700000:032x}"
        checksum = "sha256:" + hashlib.sha256(audio).hexdigest()
        media_dir = store.database_path.parent / "language-learning/media"
        media_dir.mkdir(parents=True, exist_ok=True)
        (media_dir / f"{audio_id}.wav").write_bytes(audio)
        db.execute("INSERT INTO content_items(id,language_profile_id,content_type,title,source_type,"
                   "language_code,rights_status,retention_policy,rights_policy_version,"
                   "ingestion_policy_version,content_fingerprint,status,media_artifact_id,"
                   "created_at,added_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (content_id, profile, "LOCAL_AUDIO", "Synthetic owned audio", "LOCAL_AUDIO",
                    "nb", "USER_OWNED_STORAGE_ALLOWED", "KEEP_UNTIL_USER_DELETES",
                    "language.content-rights/v1", "language.content-ingestion/v1",
                    checksum, "NEEDS_TRANSCRIPT", audio_id, STAMP, STAMP, STAMP))
        db.execute("INSERT INTO content_artifacts(id,content_id,artifact_type,original_display_name,"
                   "managed_relpath,mime_type,byte_size,checksum,storage_policy,created_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (audio_id, content_id, "AUDIO", "synthetic.wav", f"{audio_id}.wav",
                    "audio/wav", len(audio), checksum, "MANAGED_PRIVATE_FILESYSTEM", STAMP))
    return {"lemmas": lemmas, "knowledgeEvents": events, "readerTexts": texts,
            "sentences": texts, "tokens": texts * 20, "readingProgress": texts,
            "readerSessions": texts, "exposures": texts * 10,
            "listeningSessions": min(texts, 30), "listeningEvents": min(texts, 30),
            "grammarOccurrences": min(texts, 40),
            "phrasebookEntries": 100, "contentItems": min(texts, 50) + 1,
            "managedArtifacts": 1}


def measure(label, operation, *, repeats=3):
    durations = []
    error = None
    for _ in range(repeats):
        start = time.perf_counter()
        try:
            operation()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            break
        durations.append((time.perf_counter() - start) * 1000)
    if error:
        return {"operation": label, "error": error}
    return {"operation": label, "medianMs": round(statistics.median(durations), 2),
            "maxMs": round(max(durations), 2), "samples": repeats}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lemmas", type=int, default=2000)
    parser.add_argument("--texts", type=int, default=100)
    parser.add_argument("--events", type=int, default=6000)
    parser.add_argument("--reference-db", type=Path,
                        default=ROOT / "data/reference/language-reference-nb.sqlite")
    args = parser.parse_args()
    if min(args.lemmas, args.texts, args.events) < 1:
        parser.error("scale must be positive")
    with tempfile.TemporaryDirectory(prefix="language-phase12-perf-") as temporary:
        store = LanguageStore(Path(temporary) / "language-learning.sqlite")
        service = LanguageService(store)
        service.initialize()
        profile = service.ensure_bokmal_profile()["profile"]["id"]
        scale = fixture(store, profile, lemmas=args.lemmas, texts=args.texts,
                        events=args.events)
        service.create_campaign(profile, {
            "name": "Synthetic study campaign", "targetDate": "2027-05-01",
            "milestones": [{"type": "READER_TEXTS_COMPLETED", "target": 50}],
        })
        scale["campaignDefinitions"] = 1
        benchmark = service.start_benchmark(profile)["data"]
        content, _ = load_content()
        answers = {item["id"]: item["answer"] for item in content["forms"][benchmark["formId"]]}
        for item in benchmark["items"]:
            service.benchmark_response(profile, benchmark["id"], {
                "itemId": item["id"], "response": answers[item["id"]],
            })
        service.complete_benchmark(profile, benchmark["id"])
        with store.connection() as db:
            completed = dict(db.execute("SELECT * FROM benchmark_runs WHERE id=?", (benchmark["id"],)).fetchone())
            responses = [dict(row) for row in db.execute(
                "SELECT * FROM benchmark_responses WHERE run_id=?", (benchmark["id"],))]
            for n in range(39):
                row = dict(completed)
                row["id"] = f"{1800000+n:032x}"
                row["kind"] = "CHECKPOINT"
                row["started_at"] = f"2026-08-{n % 28 + 1:02d}T12:00:00Z"
                row["completed_at"] = row["started_at"]
                keys = list(row)
                db.execute("INSERT INTO benchmark_runs(" + ",".join(keys) + ") VALUES(" +
                           ",".join("?" for _ in keys) + ")", list(row.values()))
                db.executemany("INSERT INTO benchmark_responses(run_id,item_id,dimension,response_json,"
                               "environment_json,answered_at) VALUES(?,?,?,?,?,?)", [
                                   (row["id"], response["item_id"], response["dimension"],
                                    response["response_json"], response["environment_json"],
                                    row["completed_at"]) for response in responses
                               ])
        scale["benchmarkRuns"] = 40
        scale["benchmarkResponses"] = 640
        cloze = ClozeService(service, args.reference_db)
        service.attach_cloze_service(cloze)
        if args.reference_db.is_file():
            prior = service.start_cloze_session(profile, {
                "mode": "FAST_TRACK", "trackKey": "FAST_TRACK_1", "itemCount": 50,
                "seed": "phase12-history",
            })["data"]["session"]
            attempts = 0
            while item := prior["currentItem"]:
                prior = service.submit_cloze_attempt(prior["id"], {
                    "itemIndex": item["index"], "itemFingerprint": item["fingerprint"],
                    "action": "SKIP", "responseMs": 250,
                    "idempotencyKey": f"phase12-history-{attempts}",
                })["data"]["session"]
                attempts += 1
            scale["clozeSessions"] = 1
            scale["clozeAttempts"] = attempts
        else:
            scale["clozeSessions"] = 0
            scale["clozeAttempts"] = 0
        service.gamification_service.reconcile_profile(profile)
        with store.connection() as db:
            scale["gamificationAwards"] = db.execute(
                "SELECT COUNT(*) FROM gamification_awards WHERE language_profile_id=?", (profile,)
            ).fetchone()[0]
        text_id = f"{100000:032x}"
        lemma_id = f"{1:032x}"
        content_id = f"{500000:032x}"
        pack = service.curriculum_service.active_packs()[0]
        pack_id = pack["pack"]["id"]
        version = pack["pack"]["version"]
        operations = [
            ("vocabulary search", lambda: service.search_lemmas(profile, query="ord", limit=50)),
            ("lemma detail", lambda: service.get_lemma(lemma_id)),
            ("Reader library", lambda: service.list_texts(profile, limit=50)),
            ("Reader text", lambda: service.get_text(text_id)),
            ("Reader progress/history", lambda: store.get_text(text_id)),
            ("Cloze tracks", lambda: service.cloze_tracks(profile)),
            ("Listening library", lambda: store.list_listening_materials(profile)),
            ("Listening progress", lambda: service.listening_progress(text_id, profile_id=profile)),
            ("Listening detail", lambda: service.get_text(text_id)),
            ("Inbox landing", lambda: service.content_items(profile)),
            ("Inbox detail", lambda: service.content_detail(content_id)),
            ("Managed media metadata", lambda: service.content_media_file(f"{1600000:032x}")),
            ("Grammar landing", lambda: service.grammar_summary(profile)),
            ("Grammar pattern", lambda: service.grammar_summary(profile, "A1_BASIC_MAIN_CLAUSE_ORDER")),
            ("Benchmarks landing", lambda: service.benchmark_runs(profile)),
            ("Benchmark results", lambda: service.benchmark_run(profile, benchmark["id"])),
            ("Norway preparation", lambda: service.norway_preparation(profile)),
            ("Statistics", lambda: service.statistics(profile)),
            ("Overview", lambda: service.overview(profile)),
            ("Goals", lambda: service.list_goals(profile)),
            ("Gamification", lambda: service.gamification(profile)),
            ("Curriculum landing", lambda: service.curriculum(profile)),
            ("Curriculum detail", lambda: service.curriculum_pack(profile, pack_id, version)),
            ("Phrasebook", lambda: service.list_phrasebook_entries(profile)),
            ("Anki local status", lambda: service.anki_sync_service.status(profile, probe=False)),
            ("Anki local snapshot", lambda: store.anki_profile_summary(profile)),
        ]
        operations += [(f"Study Session {minutes}", lambda minutes=minutes: service.study_session(profile, minutes))
                       for minutes in (10, 20, 30)]
        if args.reference_db.is_file():
            operations += [
                ("Reference targets", lambda: cloze.reference.targets(1, 500)),
                ("Reference sentence lookup", lambda: cloze.reference.sentence_candidates_batch(
                    [row["id"] for row in cloze.reference.targets(1, 10)])),
                ("Fast Track 50", lambda: service.start_cloze_session(profile, {
                    "mode": "FAST_TRACK", "trackKey": "FAST_TRACK_1", "itemCount": 50,
                    "seed": "phase12-performance",
                })),
                ("Shared Review 50", lambda: service.start_cloze_session(profile, {
                    "mode": "REVIEW", "itemCount": 50, "seed": "phase12-performance",
                })),
            ]
        results = [measure(label, fn) for label, fn in operations]
        operation_root = Path(temporary) / "backup-packages"
        start = time.perf_counter()
        package = create_backup(store.database_path, operation_root, project_root=ROOT,
                                reference_db=args.reference_db)
        results.append({"operation": "backup creation", "elapsedMs": round((time.perf_counter()-start)*1000, 2),
                        "samples": 1})
        start = time.perf_counter()
        validation = validate_backup(package, project_root=ROOT, reference_db=args.reference_db)
        results.append({"operation": "backup validation", "elapsedMs": round((time.perf_counter()-start)*1000, 2),
                        "samples": 1, "status": validation["status"]})
        start = time.perf_counter()
        restored = restore_backup(package, Path(temporary) / "clean-restore", project_root=ROOT,
                                  reference_db=args.reference_db)
        restored_store = LanguageStore(Path(restored["target"]) / "data" / "language-learning.sqlite")
        if restored_store.export_data()["data"] != store.export_data()["data"]:
            raise RuntimeError("Clean restore differs from the synthetic durable state")
        results.append({"operation": "clean restore", "elapsedMs": round((time.perf_counter()-start)*1000, 2),
                        "samples": 1, "status": restored["status"], "logicalStateEqual": True})
        print(json.dumps({"measuredAt": datetime.now(timezone.utc).isoformat(),
                          "fixture": scale, "results": results}, indent=2))
        return 1 if any("error" in row for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
