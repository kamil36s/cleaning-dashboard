"""HTR provider abstraction and the eScriptorium 26.04 REST adapter."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from abc import ABC, abstractmethod
from pathlib import Path


class HtrProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "provider_error", status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


class HtrProvider(ABC):
    """Stable dashboard-facing provider contract."""

    @abstractmethod
    def health_check(self) -> dict: ...

    @abstractmethod
    def create_document(self, name: str) -> dict: ...

    @abstractmethod
    def upload_page(self, document_id: str, path: Path, mime_type: str) -> dict: ...

    @abstractmethod
    def segment_page(
        self,
        document_id: str,
        page_ids: list[str],
        model_id: str | None = None,
        *,
        override: bool = False,
    ) -> dict: ...

    @abstractmethod
    def rotate_page(self, document_id: str, page_id: str, angle: int) -> dict: ...

    @abstractmethod
    def delete_page(self, document_id: str, page_id: str) -> dict: ...

    @abstractmethod
    def transcribe_page(
        self,
        document_id: str,
        page_ids: list[str],
        model_id: str,
        transcription_id: str,
    ) -> dict: ...

    @abstractmethod
    def get_page_lines(
        self, document_id: str, page_id: str, transcription_id: str | None = None
    ) -> list[dict]: ...

    @abstractmethod
    def update_line_transcription(
        self,
        document_id: str,
        page_id: str,
        line_transcription_id: str,
        text: str,
    ) -> dict: ...

    @abstractmethod
    def start_recognition_training(self, document_id: str, payload: dict) -> dict: ...

    @abstractmethod
    def start_segmentation_training(self, document_id: str, payload: dict) -> dict: ...

    @abstractmethod
    def get_training_job(self, document_id: str) -> dict: ...

    @abstractmethod
    def list_training_jobs(self, document_id: str | None = None) -> list[dict]: ...

    @abstractmethod
    def list_task_groups(self, document_id: str) -> list[dict]: ...

    @abstractmethod
    def list_models(self, document_id: str | None = None) -> list[dict]: ...

    @abstractmethod
    def activate_model(self, model_id: str) -> dict: ...

    @abstractmethod
    def cancel_training(self, model_id: str) -> dict: ...

    @abstractmethod
    def delete_model(self, model_id: str) -> dict: ...

    @abstractmethod
    def export_document(self, document_id: str, payload: dict) -> dict: ...


def _multipart_body(fields: dict, files: list[tuple[str, Path, str]]) -> tuple[bytes, str]:
    boundary = f"----journal-htr-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for field_name, path, mime_type in files:
        safe_name = path.name.replace('"', "")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{safe_name}"\r\n'
                ).encode(),
                f"Content-Type: {mime_type}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class EscriptoriumProvider(HtrProvider):
    """Adapter verified against the official eScriptorium 26.04 source."""

    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        project_slug: str,
        main_script: str = "Latin",
        timeout: float = 20,
    ):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_token = str(api_token or "").strip()
        self.project_slug = str(project_slug or "").strip()
        self.main_script = str(main_script or "Latin").strip()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(
            self.base_url and self.api_token and self.project_slug and self.main_script
        )

    def _url(self, path: str, query: dict | None = None) -> str:
        url = f"{self.base_url}/api/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        body: bytes | None = None,
        content_type: str = "application/json",
        query: dict | None = None,
        timeout: float | None = None,
    ):
        if not self.configured:
            raise HtrProviderError(
                "eScriptorium is not fully configured",
                code="provider_not_configured",
                status=503,
            )
        data = body
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Token {self.api_token}",
        }
        if data is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(
            self._url(path, query), data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
                if not raw:
                    return {}
                content_header = response.headers.get("Content-Type", "")
                if "json" not in content_header:
                    return {"raw": raw, "contentType": content_header}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read(8192).decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
            except json.JSONDecodeError:
                detail = {"detail": raw[:500]}
            raise HtrProviderError(
                f"eScriptorium HTTP {exc.code}: {detail}",
                code="escriptorium_http_error",
                status=502,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HtrProviderError(
                f"Cannot reach local eScriptorium: {exc}",
                code="escriptorium_offline",
                status=503,
            ) from exc

    @staticmethod
    def _items(payload) -> list[dict]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            return payload["results"]
        return []

    def _list_all(self, path: str, query: dict | None = None) -> list[dict]:
        payload = self._request("GET", path, query=query)
        result = self._items(payload)
        while isinstance(payload, dict) and payload.get("next"):
            next_url = payload["next"]
            parsed = urllib.parse.urlparse(next_url)
            next_query = dict(urllib.parse.parse_qsl(parsed.query))
            payload = self._request("GET", parsed.path.removeprefix("/api/"), query=next_query)
            result.extend(self._items(payload))
        return result

    def health_check(self) -> dict:
        started = time.monotonic()
        payload = self._request("GET", "")
        return {
            "online": True,
            "latencyMs": round((time.monotonic() - started) * 1000),
            "api": bool(payload is not None),
            "version": "26.04",
            "krakenVersion": "7.x",
        }

    def create_document(self, name: str) -> dict:
        return self._request(
            "POST",
            "documents/",
            payload={
                "name": name,
                "project": self.project_slug,
                "main_script": self.main_script,
            },
        )

    def upload_page(self, document_id: str, path: Path, mime_type: str) -> dict:
        if mime_type == "application/pdf":
            body, content_type = _multipart_body(
                {"mode": "pdf", "name": path.stem}, [("upload_file", path, mime_type)]
            )
            return self._request(
                "POST",
                f"documents/{document_id}/import/",
                body=body,
                content_type=content_type,
                timeout=120,
            )
        body, content_type = _multipart_body({}, [("image", path, mime_type)])
        return self._request(
            "POST",
            f"documents/{document_id}/parts/",
            body=body,
            content_type=content_type,
            timeout=120,
        )

    def segment_page(
        self,
        document_id: str,
        page_ids: list[str],
        model_id: str | None = None,
        *,
        override: bool = False,
    ) -> dict:
        payload: dict = {
            "parts": page_ids,
            "steps": "both",
            "override": bool(override),
            "text_direction": "horizontal-lr",
        }
        if model_id:
            payload["model"] = model_id
        return self._request("POST", f"documents/{document_id}/segment/", payload=payload)

    def rotate_page(self, document_id: str, page_id: str, angle: int) -> dict:
        return self._request(
            "POST",
            f"documents/{document_id}/parts/{page_id}/rotate/",
            payload={"angle": angle},
        )

    def delete_page(self, document_id: str, page_id: str) -> dict:
        return self._request(
            "DELETE", f"documents/{document_id}/parts/{page_id}/"
        )

    def ensure_transcription(self, document_id: str, name: str = "Journal HTR") -> dict:
        transcriptions = self._list_all(f"documents/{document_id}/transcriptions/")
        match = next((item for item in transcriptions if item.get("name") == name), None)
        if match:
            return match
        return self._request(
            "POST", f"documents/{document_id}/transcriptions/", payload={"name": name}
        )

    def transcribe_page(
        self,
        document_id: str,
        page_ids: list[str],
        model_id: str,
        transcription_id: str,
    ) -> dict:
        return self._request(
            "POST",
            f"documents/{document_id}/transcribe/",
            payload={
                "parts": page_ids,
                "model": model_id,
                "transcription": transcription_id,
            },
        )

    def get_page_lines(
        self, document_id: str, page_id: str, transcription_id: str | None = None
    ) -> list[dict]:
        lines = self._list_all(f"documents/{document_id}/parts/{page_id}/lines/")
        transcription_rows: dict[str, dict] = {}
        if transcription_id:
            rows = self._list_all(
                f"documents/{document_id}/parts/{page_id}/transcriptions/",
                {"transcription": transcription_id},
            )
            transcription_rows = {str(item.get("line")): item for item in rows}
        normalized = []
        for line in lines:
            row = transcription_rows.get(str(line.get("pk")), {})
            normalized.append(
                {
                    "externalLineId": str(line.get("pk")),
                    "externalTranscriptionId": (
                        str(row.get("pk")) if row.get("pk") is not None else None
                    ),
                    "lineOrder": line.get("order") or 0,
                    "geometry": {
                        "baseline": line.get("baseline"),
                        "mask": line.get("mask"),
                        "region": line.get("region"),
                        "typology": line.get("typology"),
                    },
                    "predictedText": row.get("content") or "",
                    "confidence": row.get("avg_confidence"),
                }
            )
        return normalized

    def update_line_transcription(
        self,
        document_id: str,
        page_id: str,
        line_transcription_id: str,
        text: str,
    ) -> dict:
        return self._request(
            "PATCH",
            (
                f"documents/{document_id}/parts/{page_id}/transcriptions/"
                f"{line_transcription_id}/"
            ),
            payload={"content": text},
        )

    def start_recognition_training(self, document_id: str, payload: dict) -> dict:
        request_payload = {
            "parts": payload["parts"],
            "transcription": payload["transcription"],
            "model_name": payload["modelName"],
            "override": False,
        }
        if payload.get("baseModelId"):
            request_payload["model"] = payload["baseModelId"]
        return self._request(
            "POST", f"documents/{document_id}/train/", payload=request_payload
        )

    def start_segmentation_training(self, document_id: str, payload: dict) -> dict:
        request_payload = {
            "parts": payload["parts"],
            "model_name": payload["modelName"],
            "override": False,
        }
        if payload.get("baseModelId"):
            request_payload["model"] = payload["baseModelId"]
        return self._request(
            "POST", f"documents/{document_id}/segtrain/", payload=request_payload
        )

    def get_training_job(self, document_id: str) -> dict:
        tasks = self._list_all("tasks/", {"document": document_id, "ordering": "-queued_at"})
        return tasks[0] if tasks else {}

    def list_training_jobs(self, document_id: str | None = None) -> list[dict]:
        query = {"ordering": "-queued_at"}
        if document_id:
            query["document"] = document_id
        reports = self._list_all("tasks/", query)
        grouped = {}
        for report in reports:
            if report.get("method") != "core.tasks.train":
                continue
            match = re.search(
                r"celery task ([a-f0-9-]{36})",
                str(report.get("label") or ""),
                re.IGNORECASE,
            )
            if not match:
                continue
            task_id = match.group(1)
            item = grouped.setdefault(
                task_id,
                {
                    "taskId": task_id,
                    "workflowState": 0,
                    "queuedAt": report.get("queued_at"),
                    "startedAt": report.get("started_at"),
                    "doneAt": report.get("done_at"),
                    "messages": [],
                    "workflowStates": [],
                },
            )
            state = int(report.get("workflow_state") or 0)
            item["workflowStates"].append(state)
            for key, source in (
                ("queuedAt", "queued_at"),
                ("startedAt", "started_at"),
                ("doneAt", "done_at"),
            ):
                if not item.get(key) and report.get(source):
                    item[key] = report[source]
            if report.get("messages"):
                item["messages"].append(str(report["messages"])[:500])
        for item in grouped.values():
            states = item.pop("workflowStates")
            if 2 in states:
                item["workflowState"] = 2
            elif 4 in states:
                item["workflowState"] = 4
            elif 1 in states:
                item["workflowState"] = 1
            elif states and all(state == 3 for state in states):
                item["workflowState"] = 3
            else:
                item["workflowState"] = 0
        return list(grouped.values())

    def list_task_groups(self, document_id: str) -> list[dict]:
        return self._list_all(f"documents/{document_id}/task_groups/")

    def list_models(self, document_id: str | None = None) -> list[dict]:
        query = {"documents": document_id} if document_id else None
        return self._list_all("models/", query)

    def activate_model(self, model_id: str) -> dict:
        # eScriptorium does not expose a concept of one globally active model.
        # Activation belongs to the dashboard and is intentionally stored locally.
        return {
            "externalModelId": str(model_id),
            "providerChanged": False,
            "reason": "eScriptorium 26.04 has no active-model endpoint",
        }

    def cancel_training(self, model_id: str) -> dict:
        return self._request("POST", f"models/{model_id}/cancel_training/", payload={})

    def delete_model(self, model_id: str) -> dict:
        return self._request("DELETE", f"models/{model_id}/")

    def export_document(self, document_id: str, payload: dict) -> dict:
        return self._request(
            "POST", f"documents/{document_id}/export/", payload=payload
        )


class FakeHtrProvider(HtrProvider):
    """Deterministic local provider used only by tests and explicit demo mode."""

    configured = True

    def __init__(self):
        self.documents: dict[str, dict] = {}
        self.pages: dict[str, dict] = {}
        self.models = [
            {
                "pk": "fake-base-recognition",
                "name": "Fake base recognition",
                "job": "Recognize",
                "training": False,
                "accuracy_percent": 0,
            },
            {
                "pk": "fake-base-segmentation",
                "name": "Fake base segmentation",
                "job": "Segment",
                "training": False,
                "accuracy_percent": 0,
            },
        ]

    def health_check(self) -> dict:
        return {
            "online": True,
            "latencyMs": 0,
            "api": True,
            "version": "fake",
            "krakenVersion": "fake",
            "testProvider": True,
        }

    def create_document(self, name: str) -> dict:
        pk = f"doc-{len(self.documents) + 1}"
        self.documents[pk] = {"pk": pk, "name": name}
        return self.documents[pk]

    def upload_page(self, document_id: str, path: Path, mime_type: str) -> dict:
        pk = f"part-{len(self.pages) + 1}"
        self.pages[pk] = {
            "pk": pk,
            "document": document_id,
            "name": path.name,
            "mime": mime_type,
        }
        return self.pages[pk]

    def segment_page(
        self,
        document_id: str,
        page_ids: list[str],
        model_id: str | None = None,
        *,
        override: bool = False,
    ) -> dict:
        return {"status": "ok", "parts": page_ids, "override": override}

    def rotate_page(self, document_id: str, page_id: str, angle: int) -> dict:
        return {"status": "done", "page": page_id, "angle": angle}

    def delete_page(self, document_id: str, page_id: str) -> dict:
        self.pages.pop(page_id, None)
        return {"status": "deleted", "page": page_id}

    def transcribe_page(
        self,
        document_id: str,
        page_ids: list[str],
        model_id: str,
        transcription_id: str,
    ) -> dict:
        return {"status": "ok", "parts": page_ids}

    def ensure_transcription(self, document_id: str, name: str = "Journal HTR") -> dict:
        return {"pk": f"transcription-{document_id}", "name": name}

    def get_page_lines(
        self, document_id: str, page_id: str, transcription_id: str | None = None
    ) -> list[dict]:
        return [
            {
                "externalLineId": f"{page_id}-line-{index}",
                "externalTranscriptionId": f"{page_id}-text-{index}",
                "lineOrder": index,
                "geometry": {
                    "baseline": [[20, 30 + index * 42], [620, 30 + index * 42]],
                    "mask": [
                        [18, 12 + index * 42],
                        [622, 12 + index * 42],
                        [622, 40 + index * 42],
                        [18, 40 + index * 42],
                    ],
                },
                "predictedText": [
                    "To jest wierna linia testowa.",
                    "Zażółć gęślą jaźń.",
                    "A mixed Polish and English line.",
                ][index - 1],
                "confidence": [0.91, 0.54, 0.76][index - 1],
            }
            for index in range(1, 4)
        ]

    def update_line_transcription(
        self,
        document_id: str,
        page_id: str,
        line_transcription_id: str,
        text: str,
    ) -> dict:
        return {"pk": line_transcription_id, "content": text}

    def start_recognition_training(self, document_id: str, payload: dict) -> dict:
        model = {
            "pk": f"fake-model-{len(self.models) + 1}",
            "name": payload["modelName"],
            "job": "Recognize",
            "training": False,
            "accuracy_percent": 93.5,
        }
        self.models.append(model)
        return {"status": "ok", "model": model}

    def start_segmentation_training(self, document_id: str, payload: dict) -> dict:
        model = {
            "pk": f"fake-model-{len(self.models) + 1}",
            "name": payload["modelName"],
            "job": "Segment",
            "training": False,
            "accuracy_percent": 90,
        }
        self.models.append(model)
        return {"status": "ok", "model": model}

    def get_training_job(self, document_id: str) -> dict:
        return {"workflow_state": "Done"}

    def list_training_jobs(self, document_id: str | None = None) -> list[dict]:
        return []

    def list_task_groups(self, document_id: str) -> list[dict]:
        return []

    def list_models(self, document_id: str | None = None) -> list[dict]:
        return list(self.models)

    def activate_model(self, model_id: str) -> dict:
        return {"externalModelId": model_id, "providerChanged": False}

    def cancel_training(self, model_id: str) -> dict:
        return {"status": "canceled", "model": model_id}

    def delete_model(self, model_id: str) -> dict:
        before = len(self.models)
        self.models = [
            model
            for model in self.models
            if str(model.get("pk") or model.get("id")) != str(model_id)
        ]
        if len(self.models) == before:
            raise HtrProviderError("Model not found", code="not_found", status=404)
        return {"status": "deleted", "model": model_id}

    def export_document(self, document_id: str, payload: dict) -> dict:
        return {"status": "ok", "document": document_id}


def provider_from_environment() -> HtrProvider:
    provider_name = os.environ.get("HTR_PROVIDER", "escriptorium").strip().lower()
    if provider_name == "fake":
        return FakeHtrProvider()
    if provider_name != "escriptorium":
        raise HtrProviderError(
            f"Unsupported HTR_PROVIDER: {provider_name}",
            code="unsupported_provider",
            status=503,
        )
    return EscriptoriumProvider(
        os.environ.get("ESCRIPTORIUM_BASE_URL", "http://localhost:8080"),
        os.environ.get("ESCRIPTORIUM_API_TOKEN", ""),
        project_slug=os.environ.get("ESCRIPTORIUM_PROJECT_SLUG", ""),
        main_script=os.environ.get("ESCRIPTORIUM_MAIN_SCRIPT", "Latin"),
    )
