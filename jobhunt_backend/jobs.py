"""Durable single-daemon worker for Job Hunt collection jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
import threading
from typing import Any, Callable
import uuid

from .models import JobhuntError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def after_seconds(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, float(seconds)))).isoformat(
        timespec="seconds"
    )


class JobhuntWorker:
    """Claims persisted work transactionally and executes one bounded job at a time."""

    def __init__(
        self,
        service: Any,
        *,
        poll_interval: float = 0.25,
        lease_seconds: float = 180.0,
        max_pending_jobs: int = 1000,
    ) -> None:
        self.service = service
        self.store = service.store
        self.poll_interval = max(0.05, min(5.0, float(poll_interval)))
        self.lease_seconds = max(30.0, min(3600.0, float(lease_seconds)))
        self.max_pending_jobs = max(10, min(10000, int(max_pending_jobs)))
        self.owner = f"jobhunt-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._recovery = {"requeued": 0, "cancelled": 0, "failed": 0}
        self.service.attach_worker(self)

    def initialize(self) -> dict[str, int]:
        self._recovery = self.store.recover_worker_jobs(now=utc_now())
        self.service.ensure_nav_poll_scheduled()
        self.service.ensure_pracuj_poll_scheduled()
        self.service.ensure_jobbnorge_poll_scheduled()
        return dict(self._recovery)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self.initialize()
            self._thread = threading.Thread(
                target=self._run,
                name="jobhunt-worker",
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
            "state": "running" if thread is not None and thread.is_alive() else "stopped",
            "workerCount": 1,
            "owner": self.owner,
            "leaseSeconds": self.lease_seconds,
            "maxPendingJobs": self.max_pending_jobs,
            "startupRecovery": dict(self._recovery),
            "counts": self.store.worker_job_counts(),
        }

    def enqueue(
        self,
        *,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        priority: int = 0,
        max_attempts: int = 5,
        next_attempt_at: str | None = None,
        parent_job_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        active = sum(
            self.store.worker_job_counts()[state]
            for state in ("queued", "running", "retry_wait")
        )
        if active >= self.max_pending_jobs:
            raise JobhuntError(
                "Job Hunt worker queue is full", status=429, code="jobhunt_worker_queue_full"
            )
        now = utc_now()
        job, reused = self.store.enqueue_worker_job(
            job_type=job_type,
            payload=payload,
            idempotency_key=idempotency_key,
            priority=priority,
            max_attempts=max_attempts,
            next_attempt_at=next_attempt_at or now,
            parent_job_id=parent_job_id,
            now=now,
        )
        self.notify()
        return job, reused

    def cancel(self, job_id: str) -> dict[str, Any]:
        result = self.store.cancel_worker_job(job_id, now=utc_now())
        self.notify()
        return result

    def _cancelled(self, job_id: str) -> bool:
        job = self.store.get_worker_job(job_id)
        return bool(not job or job.get("cancellation_requested"))

    def _progress(self, job_id: str) -> Callable[[str, float | None], None]:
        def update(stage: str, progress: float | None = None) -> None:
            self.store.renew_worker_job_lease(
                job_id,
                lease_owner=self.owner,
                lease_expires_at=after_seconds(self.lease_seconds),
                now=utc_now(),
            )
            self.store.update_worker_job_stage(
                job_id, stage=stage, progress=progress, now=utc_now()
            )

        return update

    @staticmethod
    def _retry_delay(job: dict[str, Any], error: Exception) -> float:
        explicit = getattr(error, "retry_after_seconds", None)
        if explicit is not None:
            return max(1.0, min(86400.0, float(explicit)))
        attempt = max(1, int(job.get("attempt_count") or 1))
        base = min(900.0, 5.0 * (2 ** min(attempt - 1, 8)))
        digest = hashlib.sha256(f"{job['id']}:{attempt}".encode("utf-8")).digest()
        jitter = (int.from_bytes(digest[:2], "big") / 65535.0) * min(30.0, base * 0.25)
        return base + jitter

    def _process(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        try:
            if self._cancelled(job_id):
                self.store.fail_worker_job(
                    job_id, error_class="cancelled", error_message="Cancellation requested",
                    retryable=False, next_attempt_at=None, now=utc_now(),
                )
                return
            result = self.service.run_worker_job(
                job,
                cancelled=lambda: self._cancelled(job_id),
                progress=self._progress(job_id),
            )
            if self._cancelled(job_id):
                self.store.fail_worker_job(
                    job_id, error_class="cancelled", error_message="Cancellation requested",
                    retryable=False, next_attempt_at=None, now=utc_now(),
                )
                return
            followups = list(result.pop("followups", [])) if isinstance(result, dict) else []
            self.store.complete_worker_job(
                job_id, result=result, followups=followups, now=utc_now()
            )
            self.notify()
        except Exception as exc:
            classification = str(getattr(exc, "classification", "internal") or "internal")[:100]
            retryable = bool(getattr(exc, "retryable", False))
            if isinstance(exc, JobhuntError):
                classification = str(exc.code or "validation")[:100]
                retryable = False
            delay = self._retry_delay(job, exc) if retryable else 0.0
            next_attempt = after_seconds(delay) if retryable else None
            self.service.record_worker_failure(
                job, exc, classification=classification, backoff_until=next_attempt
            )
            self.store.fail_worker_job(
                job_id,
                error_class=classification,
                error_message=str(exc) or "Job Hunt worker job failed",
                retryable=retryable,
                next_attempt_at=next_attempt,
                now=utc_now(),
            )

    def run_once(self) -> dict[str, Any] | None:
        now = utc_now()
        job = self.store.claim_worker_job(
            lease_owner=self.owner,
            lease_expires_at=after_seconds(self.lease_seconds),
            now=now,
        )
        if job is None:
            return None
        self._process(job)
        return self.store.get_worker_job(job["id"])

    def _run(self) -> None:
        while not self._stop.is_set():
            if self.run_once() is not None:
                continue
            self._wake.wait(self.poll_interval)
            self._wake.clear()


__all__ = ["JobhuntWorker", "after_seconds", "utc_now"]
