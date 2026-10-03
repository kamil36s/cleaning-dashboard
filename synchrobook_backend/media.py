"""Audiobook inspection, multipart assembly, and browser/ASR preparation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path


ANALYSIS_CHUNK_SECONDS = 300


class MediaError(RuntimeError):
    pass


def _background_creation_flags() -> int:
    if os.name != "nt":
        return 0
    # Audio conversion is interactive-friendly during the day and returns to
    # normal priority only during the configured 01:00-06:00 quiet window.
    if 1 <= time.localtime().tm_hour < 6:
        return getattr(subprocess, "NORMAL_PRIORITY_CLASS", 0)
    return getattr(subprocess, "IDLE_PRIORITY_CLASS", 0)


def require_binary(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise MediaError(f"{name} is not available in PATH")
    return executable


def _run(command: list[str], message: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    # FFmpeg and ffprobe emit UTF-8 regardless of the active Windows code page.
    # Letting subprocess use CP1250 can kill its reader thread on perfectly valid
    # Polish or typographic metadata and leave stdout as None.
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False, creationflags=_background_creation_flags(),
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise MediaError(f"{message}: {detail[-1] if detail else 'unknown FFmpeg error'}")
    return result


def probe_m4b(source: Path) -> dict:
    ffprobe = require_binary("ffprobe")
    result = _run([
        ffprobe, "-v", "error", "-show_format", "-show_streams", "-show_chapters",
        "-of", "json", str(source),
    ], "ffprobe could not inspect the audio file", timeout=60)
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MediaError("ffprobe returned malformed metadata") from exc
    audio_stream = next((row for row in payload.get("streams", []) if row.get("codec_type") == "audio"), None)
    if not audio_stream:
        raise MediaError("The file does not contain an audio stream")
    duration = float((payload.get("format") or {}).get("duration") or audio_stream.get("duration") or 0)
    if duration <= 0:
        raise MediaError("The audiobook duration could not be determined")
    tags = (payload.get("format") or {}).get("tags") or {}
    chapters = []
    for index, chapter in enumerate(payload.get("chapters") or []):
        chapter_tags = chapter.get("tags") or {}
        chapters.append({
            "index": index,
            "title": chapter_tags.get("title") or chapter_tags.get("TITLE") or f"Chapter {index + 1}",
            "start": round(float(chapter.get("start_time") or 0), 3),
            "end": round(float(chapter.get("end_time") or 0), 3),
        })
    return {
        "duration": round(duration, 3), "codec": audio_stream.get("codec_name"),
        "sampleRate": int(audio_stream.get("sample_rate") or 0), "channels": audio_stream.get("channels"),
        "title": tags.get("title") or tags.get("TITLE"),
        "author": tags.get("artist") or tags.get("ARTIST") or tags.get("album_artist"),
        "language": tags.get("language") or tags.get("LANGUAGE"), "chapters": chapters,
    }


def _metadata_escape(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("\n", " ").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")


def _chapter_metadata(parts: list[dict], path: Path) -> None:
    lines = [";FFMETADATA1"]
    elapsed = 0
    for part in parts:
        start = elapsed
        elapsed += max(1, round(float(part["metadata"]["duration"]) * 1000))
        lines.extend([
            "[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={elapsed}",
            f"title={_metadata_escape(part['title'])}",
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _synthetic_chapters(parts: list[dict]) -> list[dict]:
    chapters = []
    elapsed = 0.0
    for index, part in enumerate(parts):
        start = elapsed
        elapsed += float(part["metadata"]["duration"])
        chapters.append({
            "index": index,
            "title": part["title"],
            "start": round(start, 3),
            "end": round(elapsed, 3),
        })
    return chapters


def prepare_audiobook(
    sources: list[dict], destination: Path, working_dir: Path, progress_callback=None,
) -> dict:
    """Create one chaptered M4B from naturally ordered MP3/WAV/M4B source parts."""
    if not sources:
        raise MediaError("No audiobook files were provided")
    progress_callback = progress_callback or (lambda completed, total, message: None)
    destination.parent.mkdir(parents=True, exist_ok=True)
    working_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for index, source in enumerate(sources):
        path = Path(source["path"])
        metadata = probe_m4b(path)
        title = str(source.get("title") or metadata.get("title") or path.stem).strip() or f"Chapter {index + 1}"
        parts.append({**source, "path": path, "title": title, "metadata": metadata})
        progress_callback(index + 1, len(sources), f"Sprawdzanie części audio {index + 1}/{len(sources)}")

    if len(parts) == 1 and parts[0]["path"].suffix.lower() == ".m4b":
        if destination.exists() and destination.stat().st_size:
            try:
                metadata = probe_m4b(destination)
                if float(metadata.get("duration") or 0) > 0:
                    if not metadata.get("chapters"):
                        metadata["chapters"] = _synthetic_chapters(parts)
                    return metadata
            except (MediaError, OSError, TypeError, ValueError):
                pass
        if parts[0]["path"].resolve() != destination.resolve():
            temporary = destination.with_suffix(".pending.m4b")
            temporary.unlink(missing_ok=True)
            shutil.copy2(parts[0]["path"], temporary)
            temporary.replace(destination)
        metadata = probe_m4b(destination)
        if not metadata.get("chapters"):
            metadata["chapters"] = _synthetic_chapters(parts)
        return metadata

    normalized_dir = working_dir / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    normalized = []
    for index, part in enumerate(parts):
        output = normalized_dir / f"part-{index + 1:04d}.m4a"
        if not output.exists() or not output.stat().st_size:
            temporary = output.with_suffix(".pending.m4a")
            temporary.unlink(missing_ok=True)
            _run([
                require_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(part["path"]), "-map", "0:a:0", "-vn", "-ar", "44100", "-ac", "2",
                "-c:a", "aac", "-b:a", "128k", str(temporary),
            ], f"FFmpeg could not convert audio part {index + 1}")
            temporary.replace(output)
        normalized.append(output)
        progress_callback(index + 1, len(parts), f"Konwertowanie/wznawianie części audio {index + 1}/{len(parts)}")

    concat_file = working_dir / "concat.txt"
    concat_file.write_text("".join(f"file '{path.resolve().as_posix()}'\n" for path in normalized), encoding="utf-8")
    metadata_file = working_dir / "chapters.ffmeta"
    _chapter_metadata(parts, metadata_file)
    temporary = destination.with_suffix(".pending.m4b")
    progress_callback(len(parts), len(parts), f"Scalanie {len(parts)} części i zapisywanie chapterów")
    _run([
        require_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(metadata_file), "-map", "0:a:0", "-map_metadata", "1", "-map_chapters", "1",
        "-c:a", "copy", "-movflags", "+faststart", str(temporary),
    ], "FFmpeg could not assemble the chaptered audiobook")
    temporary.replace(destination)
    metadata = probe_m4b(destination)
    if not metadata.get("chapters"):
        metadata["chapters"] = _synthetic_chapters(parts)
    shutil.rmtree(normalized_dir, ignore_errors=True)
    return metadata


def prepare_playback(source: Path, destination: Path, codec: str | None = None) -> None:
    if destination.exists() and destination.stat().st_size:
        return
    ffmpeg = require_binary("ffmpeg")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".pending.m4a")
    audio_options = ["-c:a", "copy"] if str(codec or "").lower() == "aac" else ["-c:a", "aac", "-b:a", "128k"]
    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:a:0", "-map_chapters", "0", "-vn", *audio_options, "-movflags", "+faststart", str(temporary),
    ], "FFmpeg could not prepare browser playback")
    temporary.replace(destination)


def prepare_analysis_chunks(
    source: Path, directory: Path, chunk_seconds: int = ANALYSIS_CHUNK_SECONDS,
) -> list[Path]:
    marker = directory / "complete.json"
    cached = sorted(directory.glob("chunk-*.wav")) if directory.exists() else []
    if marker.exists() and cached and all(path.stat().st_size for path in cached):
        try:
            cache_info = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError):
            cache_info = {}
        if int(cache_info.get("chunkSeconds") or 0) == chunk_seconds:
            return cached
    ffmpeg = require_binary("ffmpeg")
    directory.mkdir(parents=True, exist_ok=True)
    for partial in cached:
        partial.unlink(missing_ok=True)
    marker.unlink(missing_ok=True)
    output_pattern = directory / "chunk-%04d.wav"
    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        "-f", "segment", "-segment_time", str(chunk_seconds), "-reset_timestamps", "1", str(output_pattern),
    ], "FFmpeg could not prepare transcription chunks")
    chunks = sorted(directory.glob("chunk-*.wav"))
    if not chunks:
        raise MediaError("FFmpeg created no transcription chunks")
    marker.write_text(json.dumps({"chunkSeconds": chunk_seconds, "chunks": len(chunks)}), encoding="utf-8")
    return chunks
