"""Isolated reusable-model transcription worker for one Synchrobook audiobook."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# The worker runs next to a memory-heavy desktop app and browser.  Letting MKL,
# OpenMP and CTranslate2 create a thread pool per core can exhaust the Windows
# commit limit even though only one audiobook chunk is processed at a time.
try:
    THREAD_LIMIT = max(1, int(os.environ.get("SYNCHROBOOK_TRANSCRIBE_THREADS", "1")))
except ValueError:
    THREAD_LIMIT = 1
for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[variable] = str(THREAD_LIMIT)
os.environ["OMP_WAIT_POLICY"] = "PASSIVE"
os.environ["KMP_BLOCKTIME"] = "0"


MIB = 1024 * 1024
NIGHT_START_HOUR = 1
NIGHT_END_HOUR = 6
DAY_IDLE_SECONDS = 120
NIGHT_MIN_PHYSICAL = 1536 * MIB
NIGHT_MIN_COMMIT = 2048 * MIB
DAY_MIN_PHYSICAL = 3072 * MIB
DAY_MIN_COMMIT = 4096 * MIB
HIGH_MEMORY_MIN_PHYSICAL = 768 * MIB
HIGH_MEMORY_MIN_COMMIT = 1024 * MIB
WINDOWS_REPLACE_RETRY_DELAYS = (0.05, 0.12, 0.25, 0.5, 1.0)


def replace_file_with_retries(temporary: Path, path: Path) -> None:
    last_error = None
    for delay in (0, *WINDOWS_REPLACE_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            last_error = exc
    raise last_error


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        replace_file_with_retries(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_status(path: Path, payload: dict) -> None:
    try:
        atomic_json(path, {**payload, "pid": os.getpid(), "updatedAt": time.time()})
    except PermissionError:
        # A progress update is expendable. OneDrive and antivirus scanners can
        # briefly lock the destination on Windows; that must not abort hours of
        # otherwise healthy transcription work.
        pass


def high_memory_enabled(settings_path: Path | None) -> bool:
    if settings_path is None:
        return False
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return payload.get("highMemory") is True


def chunk_signature(chunk: dict, *, engine: str, model: str, language: str) -> str:
    path = Path(chunk["path"])
    stat = path.stat()
    payload = {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtimeNs": stat.st_mtime_ns,
        "offset": float(chunk.get("offset") or 0),
        "engine": engine,
        "model": model,
        "language": language,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_checkpoint(path: Path, signature: str) -> tuple[list[dict], str | None] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != 1 or payload.get("signature") != signature:
            return None
        rows = payload.get("segments")
        if not isinstance(rows, list):
            return None
        return rows, payload.get("detectedLanguage")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_checkpoint(path: Path, signature: str, rows: list[dict], detected_language: str | None) -> None:
    atomic_json(path, {
        "version": 1,
        "signature": signature,
        "detectedLanguage": detected_language,
        "segments": rows,
    })


def available_windows_memory() -> tuple[int, int] | None:
    if os.name != "nt":
        return None
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullAvailPhys), int(status.ullAvailPageFile)


def is_night_window(hour: int | None = None) -> bool:
    current_hour = time.localtime().tm_hour if hour is None else hour
    return NIGHT_START_HOUR <= current_hour < NIGHT_END_HOUR


def windows_user_idle_seconds() -> float | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LastInputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    ctypes.windll.kernel32.GetTickCount.restype = wintypes.DWORD
    elapsed_ms = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000


def set_resource_priority(*, night: bool) -> None:
    if os.name != "nt":
        return
    import ctypes

    # Whisper may use normal priority only in the quiet-hours window. During the
    # day IDLE_PRIORITY_CLASS lets interactive applications win CPU time.
    priority_class = 0x00000020 if night else 0x00000040
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.SetPriorityClass.restype = ctypes.c_bool
    kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), priority_class)


def trim_process_memory() -> None:
    gc.collect()
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.EmptyWorkingSet.argtypes = (ctypes.c_void_p,)
        psapi.EmptyWorkingSet(kernel32.GetCurrentProcess())
    except (AttributeError, OSError):
        pass


def wait_for_memory(
    status_path: Path, *, poll_seconds: float = 5,
    minimum_physical: int = NIGHT_MIN_PHYSICAL,
    minimum_commit: int = NIGHT_MIN_COMMIT,
    progress: float = 0,
) -> None:
    while True:
        available = available_windows_memory()
        if available is None:
            return
        physical, commit = available
        if physical >= minimum_physical and commit >= minimum_commit:
            return
        write_status(status_path, {
            "stage": "waiting_for_memory",
            "progress": progress,
            "availablePhysicalMb": round(physical / MIB),
            "availableCommitMb": round(commit / MIB),
            "requiredPhysicalMb": round(minimum_physical / MIB),
            "requiredCommitMb": round(minimum_commit / MIB),
        })
        time.sleep(poll_seconds)


def wait_for_resources(
    status_path: Path, *, progress: float, poll_seconds: float = 5,
    resource_settings: Path | None = None,
) -> None:
    while True:
        high_memory = high_memory_enabled(resource_settings)
        night = is_night_window()
        set_resource_priority(night=night or high_memory)
        idle_seconds = windows_user_idle_seconds()
        if not high_memory and not night and idle_seconds is not None and idle_seconds < DAY_IDLE_SECONDS:
            write_status(status_path, {
                "stage": "paused_for_user",
                "progress": progress,
                "idleSeconds": round(idle_seconds),
                "resumeAfterIdleSeconds": DAY_IDLE_SECONDS,
                "resourceMode": "day",
            })
            time.sleep(poll_seconds)
            continue
        minimum_physical = (
            HIGH_MEMORY_MIN_PHYSICAL if high_memory
            else NIGHT_MIN_PHYSICAL if night
            else DAY_MIN_PHYSICAL
        )
        minimum_commit = (
            HIGH_MEMORY_MIN_COMMIT if high_memory
            else NIGHT_MIN_COMMIT if night
            else DAY_MIN_COMMIT
        )
        available = available_windows_memory()
        if available is None or (available[0] >= minimum_physical and available[1] >= minimum_commit):
            return
        write_status(status_path, {
            "stage": "waiting_for_memory",
            "progress": progress,
            "availablePhysicalMb": round(available[0] / MIB),
            "availableCommitMb": round(available[1] / MIB),
            "requiredPhysicalMb": round(minimum_physical / MIB),
            "requiredCommitMb": round(minimum_commit / MIB),
            "resourceMode": "high-memory" if high_memory else "night" if night else "day",
        })
        time.sleep(poll_seconds)


def should_release_model(resource_settings: Path | None = None) -> bool:
    if high_memory_enabled(resource_settings):
        return False
    if is_night_window():
        return False
    idle_seconds = windows_user_idle_seconds()
    if idle_seconds is not None and idle_seconds < DAY_IDLE_SECONDS:
        return True
    available = available_windows_memory()
    return bool(available and (
        available[0] < DAY_MIN_PHYSICAL or available[1] < DAY_MIN_COMMIT
    ))


def load_engine(engine: str, model_name: str, device: str, compute_type: str):
    if engine == "faster-whisper":
        from faster_whisper import WhisperModel

        return WhisperModel(
            model_name, device=device, compute_type=compute_type,
            download_root=str(Path.home() / ".cache" / "huggingface" / "hub"),
            local_files_only=True,
            cpu_threads=THREAD_LIMIT,
            num_workers=1,
        )
    from voice_journal import _get_model

    return _get_model(model_name, device, allow_download=False)


def transcribe(model, engine: str, audio: Path, language: str | None) -> tuple[list[dict], str | None]:
    if engine == "faster-whisper":
        raw_segments, info = model.transcribe(
            str(audio), language=language, task="transcribe", beam_size=5,
            vad_filter=True, word_timestamps=False, condition_on_previous_text=True,
        )
        rows = [
            {"text": str(segment.text or "").strip(), "start": float(segment.start), "end": float(segment.end)}
            for segment in raw_segments if str(segment.text or "").strip()
        ]
        return rows, getattr(info, "language", None)
    result = model.transcribe(
        str(audio), language=language, task="transcribe", verbose=None,
        temperature=0.0, condition_on_previous_text=True, word_timestamps=False,
        fp16=device_is_cuda(model),
    )
    rows = [
        {"text": str(row.get("text") or "").strip(), "start": float(row.get("start") or 0), "end": float(row.get("end") or 0)}
        for row in (result or {}).get("segments", []) if str(row.get("text") or "").strip()
    ]
    return rows, (result or {}).get("language")


def device_is_cuda(model) -> bool:
    return str(getattr(model, "device", "cpu")).startswith("cuda")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--engine", choices=("openai-whisper", "faster-whisper"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--compute-type", default="auto")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--resource-settings", default="")
    args = parser.parse_args()
    status_path, output_path = Path(args.status), Path(args.output)
    resource_settings = Path(args.resource_settings) if args.resource_settings else None
    checkpoint_dir = output_path.parent / "chunk-results"
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        chunks = manifest.get("chunks") or []
        model = None
        combined = []
        detected_language = None
        for index, chunk in enumerate(chunks):
            progress = round(100 * index / max(1, len(chunks)), 2)
            signature = chunk_signature(
                chunk, engine=args.engine, model=args.model, language=args.language,
            )
            checkpoint_path = checkpoint_dir / f"{index:05d}.json"
            checkpoint = load_checkpoint(checkpoint_path, signature)
            write_status(status_path, {
                "stage": "transcribing", "chunk": index + 1, "chunks": len(chunks),
                "progress": progress,
                "resumed": checkpoint is not None,
            })
            if checkpoint is None:
                if model is not None and should_release_model(resource_settings):
                    model = None
                    trim_process_memory()
                wait_for_resources(status_path, progress=progress, resource_settings=resource_settings)
                if model is None:
                    high_memory = high_memory_enabled(resource_settings)
                    write_status(status_path, {
                        "stage": "loading_model", "progress": progress,
                        "resourceMode": "high-memory" if high_memory else "night" if is_night_window() else "day",
                    })
                    model = load_engine(args.engine, args.model, args.device, args.compute_type)
                rows, detected = transcribe(
                    model, args.engine, Path(chunk["path"]),
                    None if args.language == "auto" else args.language,
                )
                save_checkpoint(checkpoint_path, signature, rows, detected)
            else:
                rows, detected = checkpoint
            detected_language = detected_language or detected
            offset = float(chunk.get("offset") or 0)
            combined.extend({**row, "start": round(row["start"] + offset, 3), "end": round(row["end"] + offset, 3)} for row in rows)
            gc.collect()
        atomic_json(output_path, {
            "version": 1, "engine": args.engine, "model": args.model,
            "device": args.device, "language": detected_language or args.language,
            "segments": combined,
        })
        write_status(status_path, {"stage": "complete", "progress": 100})
        shutil.rmtree(checkpoint_dir, ignore_errors=True)
        return 0
    except Exception as exc:
        write_status(status_path, {"stage": "error", "error": str(exc) or exc.__class__.__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
