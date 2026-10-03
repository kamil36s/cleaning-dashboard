import json
import threading
import time
import urllib.parse
import urllib.request


class Bm365SheetsSyncer:
    def __init__(self, store, api_base, *, request_timeout=20, max_backoff=300, opener=None):
        self.store = store
        self.api_base = str(api_base or "").strip()
        self.request_timeout = request_timeout
        self.max_backoff = max_backoff
        self._opener = opener or urllib.request.urlopen
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._next_attempt = {}
        self._flush_lock = threading.Lock()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bm365-sheets-sync", daemon=True)
        self._thread.start()

    def stop(self, timeout=2):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def notify(self):
        self._wake.set()

    def _url(self, task):
        if not self.api_base:
            raise RuntimeError("BM365_API_BASE is not configured")
        parsed = urllib.parse.urlsplit(self.api_base)
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        query["action"] = f"bm365_{task['action']}"
        if task.get("row_id"):
            query["rowId"] = str(task["row_id"])
        elif task.get("planned_date"):
            query["date"] = str(task["planned_date"])
        if task["action"] == "rate":
            query["rating"] = str(task["rating"])
        return urllib.parse.urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(query),
            parsed.fragment,
        ))

    def _send(self, task):
        request = urllib.request.Request(
            self._url(task),
            headers={"Accept": "application/json", "User-Agent": "cleaning-dashboard/1.0"},
            method="GET",
        )
        with self._opener(request, timeout=self.request_timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("ok") is False:
            raise RuntimeError(str(payload.get("error") or "Google Sheets update failed"))

    def flush_once(self, *, limit=20, force=False):
        with self._flush_lock:
            now = time.monotonic()
            result = {"processed": 0, "synced": 0, "failed": 0}
            for task in self.store.pending_sync_tasks(limit=limit, include_failed=True):
                task_id = int(task["id"])
                if not force and self._next_attempt.get(task_id, 0) > now:
                    continue
                result["processed"] += 1
                try:
                    self._send(task)
                except Exception as exc:
                    self.store.finish_sync_task(task_id, error=exc)
                    attempts = int(task.get("attempts") or 0) + 1
                    self._next_attempt[task_id] = now + min(self.max_backoff, 2 ** min(attempts, 8))
                    result["failed"] += 1
                else:
                    self.store.finish_sync_task(task_id)
                    self._next_attempt.pop(task_id, None)
                    result["synced"] += 1
            result["queue"] = self.store.sync_queue_stats()
            return result

    def _run(self):
        while not self._stop.is_set():
            self.flush_once()
            self._wake.wait(timeout=2)
            self._wake.clear()
