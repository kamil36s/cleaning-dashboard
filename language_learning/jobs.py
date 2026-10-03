"""Durable, single-worker execution for Language analysis jobs."""

from __future__ import annotations

import threading
import time
from typing import Any

from .analysis.base import AnalyzerUnavailableError
from .errors import LanguageError


class LanguageJobManager:
    """Runs persisted jobs outside HTTP request threads.

    A process stop never pretends that an in-flight model call completed. Any
    RUNNING row left behind is returned to QUEUED by ``initialize`` on the next
    startup, unless cancellation had already been requested.
    """

    def __init__(
        self,
        service: Any,
        *,
        max_pending_jobs: int = 100,
        max_recovery_attempts: int = 3,
        poll_interval: float = 0.25,
    ) -> None:
        self.service = service
        self.store = service.store
        self.max_pending_jobs = max_pending_jobs
        self.max_recovery_attempts = max(1, int(max_recovery_attempts))
        self.poll_interval = max(0.01, float(poll_interval))
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._recovery = {"requeued": 0, "cancelled": 0, "failed": 0}
        self._word_audio_retry_after = 0.0
        self.service.attach_job_manager(self)

    def initialize(self) -> dict[str, int]:
        self._recovery = self.store.recover_analysis_jobs(
            max_attempts=self.max_recovery_attempts
        )
        generation = self.store.recover_generation_candidates(
            max_attempts=self.max_recovery_attempts
        )
        if generation["requeued"] or generation["failed"]:
            self._recovery["generationRequeued"] = generation["requeued"]
            self._recovery["generationFailed"] = generation["failed"]
        automatic = self.store.recover_automatic_generation_requests()
        if automatic["requeued"] or automatic["cancelled"]:
            self._recovery["automaticGenerationRequeued"] = automatic["requeued"]
            self._recovery["automaticGenerationCancelled"] = automatic["cancelled"]
        if self.service.word_audio_service:
            self._recovery["wordAudioRequeued"] = self.store.recover_word_audio_jobs(
                max_attempts=self.max_recovery_attempts
            )
            try:
                self._recovery["wordAudioQueued"] = self.service.word_audio_service.enqueue_all()
            except LanguageError:
                self._recovery["wordAudioQueued"] = 0
        return dict(self._recovery)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self.initialize()
            self._thread = threading.Thread(
                target=self._run,
                name="language-analysis-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout))

    def notify(self) -> None:
        self._wake.set()

    def status(self) -> dict[str, Any]:
        thread = self._thread
        return {
            "state": "RUNNING" if thread is not None and thread.is_alive() else "STOPPED",
            "workerCount": 1,
            "maxPendingJobs": self.max_pending_jobs,
            "maxRecoveryAttempts": self.max_recovery_attempts,
            "startupRecovery": dict(self._recovery),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next_analysis_job()
            if job is None:
                automatic = self.store.claim_next_automatic_generation()
                if automatic is not None:
                    self._process_automatic_generation(automatic)
                    continue
                candidate = self.store.claim_next_generation_candidate()
                if candidate is not None:
                    self._process_generation(candidate)
                    continue
                if self.service.word_audio_service and time.monotonic() >= self._word_audio_retry_after:
                    audio_job = self.store.claim_next_word_audio_job()
                    if audio_job is not None:
                        self._process_word_audio(audio_job)
                        continue
                self._wake.wait(self.poll_interval)
                self._wake.clear()
                continue
            self._process(job)

    def _cancelled(self, job_id: str) -> bool:
        row = self.store.get_analysis_job(job_id)
        if row["cancel_requested"]:
            self.store.mark_analysis_job_cancelled(job_id)
            return True
        return False

    def _process(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            if self._cancelled(job_id):
                return

            if job.get("analysis_domain") == "GRAMMAR":
                self.service.grammar.execute(job, lambda: self._stop.is_set() or self._cancelled(job_id))
                return

            if job["job_type"] == "REANALYSIS_COMMIT":
                self.store.update_analysis_job_stage(job_id, "LOADING_PREVIEW", 0.2)
                analysis = self.service.analysis_from_preview_job(job)
            else:
                self.store.update_analysis_job_stage(job_id, "ANALYZING", 0.1)
                analysis = self.service.analyze_for_job(job)

            # A shutdown during a model call deliberately leaves the durable
            # RUNNING row for the next startup's recovery pass.
            if self._stop.is_set():
                return
            if self._cancelled(job_id):
                return

            if job["job_type"] == "REANALYSIS_PREVIEW":
                self.store.update_analysis_job_stage(job_id, "BUILDING_PREVIEW", 0.8)
                preview = self.service.build_reanalysis_preview(job, analysis)
                if self._stop.is_set():
                    return
                if self._cancelled(job_id):
                    return
                self.store.complete_preview_job(job_id, preview)
                return

            self.store.update_analysis_job_stage(job_id, "ENRICHING_FREQUENCY", 0.75)
            frequencies = self.service.frequency_rows_for_analysis(analysis)
            if self._stop.is_set():
                return
            if self._cancelled(job_id):
                return
            self.store.update_analysis_job_stage(job_id, "COMMITTING", 0.9)
            self.store.commit_analysis_job(job_id, analysis, frequencies=frequencies)
            self.service.refresh_content_alignment(str(job["text_document_id"]))
            if self.service.word_audio_service:
                try:
                    self.service.word_audio_service.enqueue_for_text(str(job["text_document_id"]))
                except LanguageError:
                    pass
        except AnalyzerUnavailableError:
            self.store.fail_analysis_job(
                job_id,
                error_code="canonical_analyzer_unavailable",
                error_message="Canonical Bokmål analyzer is unavailable",
            )
        except LanguageError as exc:
            self.store.fail_analysis_job(
                job_id,
                error_code=exc.code,
                error_message=str(exc),
            )
        except Exception:
            self.store.fail_analysis_job(
                job_id,
                error_code="language_analysis_failed",
                error_message="Language analysis failed",
            )

    def _process_generation(self, candidate: dict[str, Any]) -> None:
        candidate_id = candidate["id"]
        try:
            result, status = self.service.generation_service.analyze(candidate_id)
            if self._stop.is_set():
                return
            self.store.complete_generation_candidate(candidate_id, result, status=status)
        except AnalyzerUnavailableError:
            self.store.fail_generation_candidate(
                candidate_id,
                error_code="canonical_analyzer_unavailable",
                error_message="Canonical Bokmål analyzer is unavailable",
            )
        except LanguageError as exc:
            self.store.fail_generation_candidate(
                candidate_id, error_code=exc.code, error_message=str(exc)
            )
        except Exception:
            self.store.fail_generation_candidate(
                candidate_id,
                error_code="generation_analysis_failed",
                error_message="Generation candidate analysis failed",
            )

    def _process_word_audio(self, job: dict[str, Any]) -> None:
        try:
            self.service.word_audio_service.process(job)
        except LanguageError as exc:
            self.store.finish_word_audio_job(job["cache_key"], error_code=exc.code)
            if exc.code in {"cloze_audio_credentials_missing", "cloze_audio_credentials_invalid",
                            "cloze_audio_quota_limit", "cloze_audio_provider_unavailable"}:
                self._word_audio_retry_after = time.monotonic() + 60
        except Exception:
            self.store.finish_word_audio_job(job["cache_key"], error_code="word_audio_generation_failed")

    def _process_automatic_generation(self, request: dict[str, Any]) -> None:
        request_id = request["id"]
        try:
            self.service.generation_service.run_automatic(request_id)
        except AnalyzerUnavailableError:
            self.store.finish_automatic_generation(
                request_id, status="FAILED", stage="ANALYSIS_FAILED",
                error_code="canonical_analyzer_unavailable",
                error_message="Canonical Bokm\u00e5l analyzer is unavailable",
            )
        except LanguageError as exc:
            self.store.finish_automatic_generation(
                request_id, status="FAILED", stage="FAILED",
                error_code=exc.code, error_message=str(exc),
            )
        except Exception:
            self.store.finish_automatic_generation(
                request_id, status="FAILED", stage="FAILED",
                error_code="automatic_generation_failed",
                error_message="Automatic generation failed",
            )


__all__ = ["LanguageJobManager"]
