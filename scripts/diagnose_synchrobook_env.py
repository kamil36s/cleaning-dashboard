"""Report the local media/Whisper stack available to Synchrobook.

This script is deliberately read-only: it never installs packages, downloads
models, or changes the active Python environment.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import platform
import shutil
import subprocess


def package_version(distribution: str, module: str | None = None) -> tuple[bool, str]:
    try:
        if module:
            importlib.import_module(module)
        return True, importlib.metadata.version(distribution)
    except Exception as exc:
        return False, f"NOT FOUND ({exc.__class__.__name__})"


def binary_version(name: str) -> tuple[bool, str]:
    executable = shutil.which(name)
    if not executable:
        return False, "NOT FOUND"
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        first_line = (result.stdout or result.stderr).splitlines()[0].strip()
        version = first_line.replace("ffmpeg version ", "").replace("ffprobe version ", "")
        return result.returncode == 0, version
    except Exception as exc:
        return False, f"ERROR ({exc.__class__.__name__})"


def emit(label: str, value: str, ok: bool) -> None:
    print(f"{label:<20} {value:<42} {'OK' if ok else 'NOT AVAILABLE'}")


def nvidia_gpu() -> tuple[bool, str]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return False, "NOT FOUND"
    try:
        result = subprocess.run(
            [executable, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return bool(names), ", ".join(names) if names else "NOT FOUND"
    except Exception as exc:
        return False, f"ERROR ({exc.__class__.__name__})"


def main() -> int:
    print("Synchrobook environment report")
    print("=" * 78)
    emit("Python", platform.python_version(), True)

    ffmpeg_ok, ffmpeg_version = binary_version("ffmpeg")
    ffprobe_ok, ffprobe_version = binary_version("ffprobe")
    emit("FFmpeg", ffmpeg_version, ffmpeg_ok)
    emit("FFprobe", ffprobe_version, ffprobe_ok)

    torch_ok, torch_version = package_version("torch", "torch")
    cuda_available = False
    cuda_version = "NOT AVAILABLE"
    gpu_ok, gpu_name = nvidia_gpu()
    if torch_ok:
        try:
            import torch

            cuda_available = bool(torch.cuda.is_available())
            cuda_version = str(torch.version.cuda or "CPU build")
            if cuda_available:
                gpu_name = str(torch.cuda.get_device_name(0))
                gpu_ok = True
        except Exception:
            pass
    emit("PyTorch", torch_version, torch_ok)
    emit("CUDA", cuda_version, cuda_available)
    emit("NVIDIA GPU", gpu_name, gpu_ok)

    packages = [
        ("PyMuPDF PDF/MOBI", "pymupdf", "pymupdf"),
        ("whisper module", "openai-whisper", "whisper"),
        ("openai-whisper", "openai-whisper", "whisper"),
        ("faster-whisper", "faster-whisper", "faster_whisper"),
        ("whisperx", "whisperx", "whisperx"),
    ]
    detected: dict[str, bool] = {}
    for label, distribution, module in packages:
        ok, version = package_version(distribution, module)
        detected[label] = ok
        emit(label, version, ok)

    if detected.get("whisperx") and cuda_available:
        recommendation = "WhisperX + CUDA"
    elif detected.get("faster-whisper") and cuda_available:
        recommendation = "Faster-Whisper + CUDA"
    elif detected.get("faster-whisper"):
        recommendation = f"Faster-Whisper + {'CUDA' if cuda_available else 'CPU (int8)'}"
    elif detected.get("openai-whisper"):
        recommendation = f"OpenAI Whisper + {'CUDA' if cuda_available else 'CPU'}"
    else:
        recommendation = "No working Whisper implementation detected"

    print("\nRecommended Synchrobook pipeline:")
    print(recommendation)
    ready = ffmpeg_ok and ffprobe_ok and (
        detected.get("openai-whisper", False) or detected.get("faster-whisper", False)
    )
    print(f"\nOverall: {'READY' if ready else 'INCOMPLETE'}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
