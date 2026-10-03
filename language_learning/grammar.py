"""Grammar orchestration and persistence. No language-specific detection rules."""
from __future__ import annotations

import hashlib
import json

from .errors import LanguageConflictError, LanguageNotFoundError, LanguageValidationError
from .grammar_parser import GrammarParser, map_canonical
from .grammar_nb import registry
from .store import canonical_json, new_id, utc_now

POLICY = "language.grammar-evidence/v1"


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def semantic_key(sentence_id, pattern, roles):
    # Detector implementation upgrades are compatible only if semantic version,
    # exact canonical span, role assignment and supporting structure stay equal.
    return fingerprint([sentence_id, pattern["patternId"], pattern["patternVersion"], roles])


class GrammarService:
    def __init__(self, language_service, parser=None):
        self.language = language_service
        self.store = language_service.store
        self.parser = parser or GrammarParser()

    def _profile(self, profile_id):
        profile_id = self.language._id(profile_id, "profileId")
        profile = self.store.get_profile(profile_id)
        catalogue, detector = registry(profile["language_code"])
        if not catalogue:
            raise LanguageValidationError("Grammar is unavailable for this language", code="GRAMMAR_LANGUAGE_UNAVAILABLE")
        return profile, catalogue, detector

    def _text(self, text_id, profile_id):
        self._profile(profile_id)
        snapshot = self.store.get_text(self.language._id(text_id, "textId"))
        if snapshot["document"]["language_profile_id"] != profile_id:
            raise LanguageConflictError("Text belongs to another profile", code="cross_profile_relationship")
        return snapshot

    def enqueue(self, text_id, payload):
        payload = self.language._object(payload)
        if set(payload) - {"languageProfileId"}:
            raise LanguageValidationError("Grammar analysis accepts only languageProfileId")
        profile_id = self.language._id(payload.get("languageProfileId"), "languageProfileId")
        snapshot = self._text(text_id, profile_id)
        doc = snapshot["document"]
        runs = [r for r in snapshot["analysisRuns"] if r["state"] == "COMPLETED"]
        if doc["processing_state"] != "ANALYZED" or not runs:
            raise LanguageConflictError("Analyze the Reader text first", code="language_text_not_analyzed")
        source = self._source(snapshot)
        _, catalogue, _ = self._profile(profile_id)
        health = self.parser.health()
        values = {"language_profile_id": profile_id, "text_document_id": text_id,
                  "job_type": "ANALYZE", "analysis_domain": "GRAMMAR", "job_version": "language.grammar-job/v1",
                  "analyzer_id": "stanza-nb-dependencies", "analyzer_version": "1.0.0",
                  "contract_version": "language.grammar-occurrence/v1", "analysis_policy_version": POLICY,
                  "frequency_provider_id": "NONE", "frequency_provider_version": "NONE", "coverage_policy_version": "NONE",
                  "content_fingerprint": doc["content_fingerprint"],
                  "analysis_fingerprint": fingerprint(["GRAMMAR", text_id, runs[-1]["id"], catalogue, health.get("provenance"), source]),
                  "request": {"canonicalAnalysisRunId": runs[-1]["id"], "source": source}}
        return self.language._enqueue_job(values)

    def _source(self, snapshot):
        doc = snapshot["document"]
        with self.store.connection() as connection:
            content = connection.execute("SELECT id,source_type,source_name,rights_status FROM content_items WHERE text_document_id=?", (doc["id"],)).fetchone()
            transcript = connection.execute("SELECT id,content_id,version,source_type,source_fingerprint FROM transcripts WHERE text_document_id=?", (doc["id"],)).fetchone()
            generated = connection.execute("SELECT id,generation_request_id FROM generation_candidates WHERE accepted_text_document_id=? AND status='ACCEPTED'", (doc["id"],)).fetchone()
        kind = "GENERATED" if generated else "TRANSCRIPT" if transcript else "AUTHENTIC" if content else "READER"
        if doc["source_type"].startswith("GENERATED") and not generated:
            raise LanguageConflictError("Only accepted generated Reader text is eligible", code="grammar_generated_not_accepted")
        return {"kind": kind, "sourceType": doc["source_type"], "sourceReference": doc["source_reference"],
                "content": dict(content) if content else None, "transcript": dict(transcript) if transcript else None,
                "generation": dict(generated) if generated else None}

    def execute(self, job, should_stop):
        snapshot = self._text(job["text_document_id"], job["language_profile_id"])
        request = json.loads(job["request_json"])
        _, catalogue, detector = self._profile(job["language_profile_id"])
        patterns = {p["patternId"]: p for p in catalogue}
        self.store.update_analysis_job_stage(job["id"], "PARSING_DEPENDENCIES", .1)
        parsed = self.parser.parse(snapshot["document"]["raw_text"])
        if should_stop():
            return
        self.store.update_analysis_job_stage(job["id"], "MAPPING_TOKENS", .6)
        mapped = map_canonical(parsed, snapshot)
        self.store.update_analysis_job_stage(job["id"], "RUNNING_DETECTORS", .7)
        occurrences = []
        for sentence in mapped:
            index = {t["index"]: t for t in sentence["tokens"]}
            for match in detector(sentence):
                pattern = patterns[match["patternId"]]
                if pattern["status"] not in {"SUPPORTED", "EXPERIMENTAL"}:
                    continue
                roles = {role: {"tokenId": token["tokenId"], "tokenOrder": token["tokenOrder"],
                                "start": token["start"], "end": token["end"], "pos": token["pos"],
                                "morphology": token["morphology"], "relation": token["relation"],
                                "headTokenId": index[token["head"]]["tokenId"] if token["head"] else None}
                         for role, token in match["roles"].items()}
                start, end = min(t["start"] for t in roles.values()), max(t["end"] for t in roles.values())
                occurrences.append((pattern, sentence["sentenceId"], start, end, roles, semantic_key(sentence["sentenceId"], pattern, roles)))
        if should_stop():
            return
        self.store.update_analysis_job_stage(job["id"], "PERSISTING", .9)
        now = utc_now()
        with self.store.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM language_jobs WHERE id=?", (job["id"],)).fetchone()
            if current["state"] != "RUNNING" or current["cancel_requested"]:
                return
            base = connection.execute("SELECT * FROM analysis_runs WHERE text_document_id=? AND state='COMPLETED' ORDER BY created_at DESC,id DESC LIMIT 1", (job["text_document_id"],)).fetchone()
            if not base or base["id"] != request["canonicalAnalysisRunId"] or base["content_fingerprint"] != job["content_fingerprint"]:
                raise LanguageConflictError("Canonical analysis changed; retry Grammar", code="STALE_GRAMMAR_ANALYSIS")
            connection.execute("INSERT INTO grammar_analysis_runs VALUES(?,?,?,?,?,?,?,?,?,?)",
                               (job["id"], job["language_profile_id"], job["text_document_id"], base["id"], canonical_json(parsed["provenance"]),
                                base["provenance_json"], canonical_json(request["source"]), canonical_json(catalogue), POLICY, now))
            for pattern, sentence_id, start, end, roles, key in occurrences:
                connection.execute("INSERT OR IGNORE INTO grammar_occurrences VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (new_id(), job["id"], job["language_profile_id"], job["text_document_id"], sentence_id,
                                    pattern["patternId"], pattern["patternVersion"], pattern["detectorId"], pattern["detectorVersion"],
                                    pattern["status"], pattern["status"] + "_RULE_MATCH", start, end, canonical_json(roles), key, now))
            connection.execute("UPDATE language_jobs SET state='COMPLETED',stage='COMPLETED',progress=1,result_json=?,completed_at=?,updated_at=? WHERE id=?",
                               (canonical_json({"grammarRunId": job["id"], "occurrenceCount": len(occurrences), "policyVersion": POLICY}), now, now, job["id"]))

    _CTE = """
    WITH runs AS (
      SELECT *, ROW_NUMBER() OVER(PARTITION BY text_document_id ORDER BY created_at DESC,rowid DESC) AS rank
      FROM grammar_analysis_runs WHERE language_profile_id=:profile
    ), reviews AS (
      SELECT *, ROW_NUMBER() OVER(PARTITION BY semantic_key ORDER BY created_at DESC,rowid DESC) AS rank
      FROM grammar_occurrence_reviews WHERE language_profile_id=:profile
    ), studied AS (
      SELECT DISTINCT e.sentence_id FROM exposure_events e JOIN study_sessions s ON s.id=e.study_session_id
      WHERE e.language_profile_id=:profile AND e.batch_idempotency_key IS NOT NULL
        AND ((e.source_type='READER' AND s.session_type='READER') OR (e.source_type='LISTENING' AND s.session_type='LISTENING'))
    ), current AS (
      SELECT o.*,COALESCE(v.decision,'UNREVIEWED') AS review_state,
             CASE WHEN s.sentence_id IS NOT NULL THEN 1 ELSE 0 END AS studied,
             r.source_provenance_json,r.parser_provenance_json,r.analyzer_provenance_json
      FROM grammar_occurrences o JOIN runs r ON r.id=o.run_id AND r.rank=1
      LEFT JOIN reviews v ON v.semantic_key=o.semantic_key AND v.rank=1
      LEFT JOIN studied s ON s.sentence_id=o.sentence_id
      WHERE o.language_profile_id=:profile
    )
    """

    def summary(self, profile_id, pattern_id=None):
        _, catalogue, _ = self._profile(profile_id)
        patterns = {p["patternId"]: dict(p) for p in catalogue}
        if pattern_id is not None and pattern_id not in patterns:
            raise LanguageNotFoundError("Grammar pattern was not found")
        with self.store.connection() as connection:
            rows = connection.execute(self._CTE + """
              SELECT pattern_id,COUNT(*) AS total,
                SUM(CASE WHEN support_status='SUPPORTED' AND review_state!='REJECTED' THEN 1 ELSE 0 END) AS authoritative,
                MAX(CASE WHEN support_status='SUPPORTED' AND review_state!='REJECTED' THEN studied ELSE 0 END) AS encountered
              FROM current GROUP BY pattern_id
            """, {"profile": profile_id}).fetchall()
        for pattern in patterns.values():
            pattern.update({"occurrenceCount": 0, "authoritativeCount": 0, "state": "NOT_DISCOVERED"})
        for row in rows:
            if row["pattern_id"] in patterns:
                patterns[row["pattern_id"]].update({"occurrenceCount": row["total"], "authoritativeCount": row["authoritative"],
                                                   "state": "ENCOUNTERED" if row["encountered"] else "DISCOVERED" if row["authoritative"] else "NOT_DISCOVERED"})
        result = {"policyVersion": POLICY, "parser": self.parser.health(), "bucketMeaning": "Practical learner scope, not certified CEFR grammar levels",
                  "items": list(patterns.values())}
        if pattern_id is not None:
            result["pattern"] = patterns[pattern_id]
            result.update(self.examples(profile_id, pattern_id=pattern_id))
        else:
            result["previews"] = self.examples(profile_id, previews=True)["examples"]
        return result

    def examples(self, profile_id, *, pattern_id=None, text_id=None, previews=False):
        with self.store.connection() as connection:
            preview_cte = ", ranked AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY pattern_id ORDER BY created_at DESC,id) AS preview_rank FROM current) " if previews else ""
            rows = connection.execute(self._CTE + preview_cte + """
              SELECT c.*,s.exact_text,s.source_start AS sentence_start,d.title,d.source_type
              FROM """ + ("ranked" if previews else "current") + """ c JOIN text_sentences s ON s.id=c.sentence_id JOIN text_documents d ON d.id=c.text_document_id
              WHERE (:pattern IS NULL OR c.pattern_id=:pattern) AND (:text IS NULL OR c.text_document_id=:text)
              """ + (" AND preview_rank=1 " if previews else "") + """ ORDER BY c.created_at DESC,c.text_document_id,c.source_start,c.id LIMIT 201
            """, {"profile": profile_id, "pattern": pattern_id, "text": text_id}).fetchall()
        examples = []
        for row in rows[:200]:
            example = self.store.api_row(dict(row))
            example["state"] = "ENCOUNTERED" if row["studied"] and row["review_state"] != "REJECTED" and row["support_status"] == "SUPPORTED" else "DISCOVERED" if row["support_status"] == "SUPPORTED" and row["review_state"] != "REJECTED" else "NOT_DISCOVERED"
            examples.append(example)
        return {"examples": examples, "hasMore": len(rows) > 200}

    def text_status(self, text_id, profile_id):
        self._text(text_id, profile_id)
        with self.store.connection() as connection:
            row = connection.execute("SELECT * FROM language_jobs WHERE text_document_id=? AND analysis_domain='GRAMMAR' ORDER BY created_at DESC,rowid DESC LIMIT 1", (text_id,)).fetchone()
        return {"parser": self.parser.health(), "status": row["state"] if row else "NOT_ANALYZED",
                "job": self.language._public_job(dict(row)) if row else None, **self.examples(profile_id, text_id=text_id)}

    def review(self, occurrence_id, payload):
        occurrence_id = self.language._id(occurrence_id, "occurrenceId")
        payload = self.language._object(payload)
        if set(payload) - {"languageProfileId", "decision"}:
            raise LanguageValidationError("Unsupported Grammar review fields")
        profile_id = self.language._id(payload.get("languageProfileId"), "languageProfileId")
        self._profile(profile_id)
        decision = payload.get("decision")
        if decision not in {"CONFIRMED", "REJECTED", "UNREVIEWED"}:
            raise LanguageValidationError("Invalid detector review decision")
        with self.store.connection() as connection:
            row = connection.execute("SELECT * FROM grammar_occurrences WHERE id=?", (occurrence_id,)).fetchone()
            if not row:
                raise LanguageNotFoundError("Grammar occurrence was not found")
            if row["language_profile_id"] != profile_id:
                raise LanguageConflictError("Occurrence belongs to another profile", code="cross_profile_relationship")
            connection.execute("INSERT INTO grammar_occurrence_reviews VALUES(?,?,?,?,?,?)",
                               (new_id(), occurrence_id, profile_id, row["semantic_key"], decision, utc_now()))
        return {"occurrenceId": occurrence_id, "decision": decision, "knowledgeMutation": "NONE"}
