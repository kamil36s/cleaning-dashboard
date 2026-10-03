"""Isolated local Whisper worker used by the voice journal job queue."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voice_journal import (  # noqa: E402
    _get_model,
    normalize_transcript_segments,
    normalize_transcription_data_segments,
)
from voice_journal_engines import (  # noqa: E402
    FASTER_ENGINE,
    OPENAI_ENGINE,
    faster_worker_options,
)


def _optional_float(value):
    try:
        return round(float(value), 6) if value is not None else None
    except (TypeError, ValueError):
        return None


def normalize_faster_segments(raw_segments) -> tuple[str, list[dict]]:
    segments = []
    transcript_parts = []
    for index, raw in enumerate(raw_segments):
        text = str(getattr(raw, "text", "") or "").strip()
        if not text:
            continue
        segment_id = f"segment-{index + 1}"
        words = []
        for word_index, word in enumerate(getattr(raw, "words", None) or []):
            word_text = str(getattr(word, "word", "") or "")
            words.append({
                "id": f"{segment_id}-word-{word_index + 1}",
                "text": word_text,
                "originalText": word_text,
                "correctedText": word_text,
                "start": _optional_float(getattr(word, "start", None)),
                "end": _optional_float(getattr(word, "end", None)),
                "probability": _optional_float(getattr(word, "probability", None)),
                "correctionStatus": "original",
                "manuallyChanged": False,
            })
        segment = {
            "id": segment_id,
            "start": _optional_float(getattr(raw, "start", None)),
            "end": _optional_float(getattr(raw, "end", None)),
            "text": text,
            "originalText": text,
            "correctedText": text,
            "avgLogprob": _optional_float(getattr(raw, "avg_logprob", None)),
            "noSpeechProbability": _optional_float(getattr(raw, "no_speech_prob", None)),
            "correctionStatus": "original",
            "words": words,
        }
        segments.append(segment)
        transcript_parts.append(text)
    return " ".join(transcript_parts).strip(), segments


def write_json_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def run(args) -> int:
    status_path = Path(args.status_file).resolve()
    result_path = Path(args.result_file).resolve()
    try:
        options = json.loads(Path(args.options_file).read_text(encoding="utf-8"))
        if not isinstance(options, dict):
            raise ValueError("Transcription options must be a JSON object")
        allow_download = getattr(args, "allow_model_download", "false") == "true"
        write_json_atomic(status_path, {"stage": "loading_model"})
        engine = getattr(args, "engine", OPENAI_ENGINE)
        if engine == FASTER_ENGINE:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("Faster-Whisper is not installed in this Python environment") from exc
            model = WhisperModel(
                args.model,
                device=args.device,
                compute_type=getattr(args, "compute_type", "auto"),
                download_root=str(Path.home() / ".cache" / "huggingface" / "hub"),
                local_files_only=not allow_download,
            )
        else:
            model = _get_model(args.model, args.device, allow_download=allow_download)
        write_json_atomic(status_path, {"stage": "transcribing"})
        started = time.perf_counter()
        language = None if args.language == "auto" else args.language
        if engine == FASTER_ENGINE:
            raw_segments, info = model.transcribe(
                args.audio,
                language=language,
                task=args.task,
                **faster_worker_options(options),
            )
            transcript, rich_segments = normalize_faster_segments(raw_segments)
            segments = [
                {"start": segment["start"], "end": segment["end"], "text": segment["text"]}
                for segment in rich_segments
            ]
            engine_metadata = {
                "detectedLanguage": getattr(info, "language", None),
                "languageProbability": _optional_float(getattr(info, "language_probability", None)),
                "durationAfterVad": _optional_float(getattr(info, "duration_after_vad", None)),
            }
        else:
            result = model.transcribe(
                args.audio,
                language=language,
                task=args.task,
                verbose=None,
                **options,
            )
            transcript = str((result or {}).get("text") or "").strip()
            segments = normalize_transcript_segments(result)
            rich_segments = normalize_transcription_data_segments(result)
            engine_metadata = {"detectedLanguage": (result or {}).get("language")}
        elapsed = time.perf_counter() - started
        write_json_atomic(result_path, {
            "ok": True,
            "transcript": transcript,
            "transcriptSegments": segments,
            "transcriptionDataSegments": rich_segments,
            "engineMetadata": engine_metadata,
            "transcriptionDurationSeconds": round(elapsed, 3),
        })
        return 0
    except Exception as exc:
        write_json_atomic(result_path, {
            "ok": False,
            "error": str(exc) or exc.__class__.__name__,
        })
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--engine", choices=(OPENAI_ENGINE, FASTER_ENGINE), default=OPENAI_ENGINE)
    parser.add_argument("--model", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--compute-type", default="auto")
    parser.add_argument("--allow-model-download", choices=("true", "false"), default="false")
    parser.add_argument("--options-file", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--result-file", required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
