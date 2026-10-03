from __future__ import annotations

import base64
import binascii
import json
import os
import time
from pathlib import Path


MAX_POSTCARD_BYTES = 12 * 1024 * 1024
SUPPORTED_IMAGES = {
    "image/jpeg": (".jpg", lambda value: value.startswith(b"\xff\xd8\xff")),
    "image/png": (".png", lambda value: value.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (".webp", lambda value: len(value) >= 12 and value[:4] == b"RIFF" and value[8:12] == b"WEBP"),
}


class JourneyPostcardStore:
    def __init__(self, root, checkpoint_ids):
        self.root = Path(root)
        self.checkpoint_ids = set(checkpoint_ids)
        self.manifest_path = self.root / "manifest.json"

    def _read_manifest(self):
        if not self.manifest_path.exists():
            return {"version": 1, "postcards": {}}
        try:
            document = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "postcards": {}}
        postcards = document.get("postcards")
        return {"version": 1, "postcards": postcards if isinstance(postcards, dict) else {}}

    def _write_manifest(self, document):
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.manifest_path)

    def list(self):
        manifest = self._read_manifest()
        result = []
        for checkpoint_id, item in manifest["postcards"].items():
            filename = str(item.get("filename") or "")
            if checkpoint_id not in self.checkpoint_ids or not filename:
                continue
            path = self.root / filename
            if not path.is_file():
                continue
            result.append({
                "checkpointId": checkpoint_id,
                "mimeType": item.get("mimeType"),
                "uploadedAt": item.get("uploadedAt"),
                "originalName": item.get("originalName"),
                "size": path.stat().st_size,
                "imageUrl": f"/api/live-workout/journey/postcards/{checkpoint_id}/image",
            })
        return sorted(result, key=lambda item: item["checkpointId"])

    def image(self, checkpoint_id):
        item = self._read_manifest()["postcards"].get(checkpoint_id)
        if not item:
            return None
        path = self.root / str(item.get("filename") or "")
        if not path.is_file() or path.parent.resolve() != self.root.resolve():
            return None
        return path, str(item.get("mimeType") or "application/octet-stream")

    def save(self, checkpoint_id, original_name, mime_type, encoded_data):
        if checkpoint_id not in self.checkpoint_ids:
            raise ValueError("Unknown journey checkpoint")
        mime_type = str(mime_type or "").lower().split(";", 1)[0].strip()
        image_config = SUPPORTED_IMAGES.get(mime_type)
        if not image_config:
            raise ValueError("Postcard must be a JPEG, PNG or WebP image")
        try:
            payload = base64.b64decode(str(encoded_data or ""), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Postcard image is not valid base64") from exc
        if not payload or len(payload) > MAX_POSTCARD_BYTES:
            raise ValueError("Postcard image must be smaller than 12 MB")
        extension, signature_matches = image_config
        if not signature_matches(payload):
            raise ValueError("Postcard file content does not match its image type")

        self.root.mkdir(parents=True, exist_ok=True)
        filename = f"{checkpoint_id}{extension}"
        target = self.root / filename
        temporary = self.root / f".{filename}.tmp"
        temporary.write_bytes(payload)
        os.replace(temporary, target)

        manifest = self._read_manifest()
        previous = manifest["postcards"].get(checkpoint_id) or {}
        previous_filename = str(previous.get("filename") or "")
        manifest["postcards"][checkpoint_id] = {
            "filename": filename,
            "mimeType": mime_type,
            "originalName": Path(str(original_name or filename)).name[:180],
            "uploadedAt": int(time.time() * 1000),
        }
        self._write_manifest(manifest)
        if previous_filename and previous_filename != filename:
            previous_path = self.root / previous_filename
            if previous_path.is_file() and previous_path.parent.resolve() == self.root.resolve():
                previous_path.unlink()
        return next(item for item in self.list() if item["checkpointId"] == checkpoint_id)
