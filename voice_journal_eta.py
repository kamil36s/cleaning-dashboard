"""Conservative ETA calculations for local voice-journal transcription jobs."""

from __future__ import annotations

import math
import statistics


def _valid_numbers(values):
    valid = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            valid.append(number)
    return valid


def _rounded_range(low_seconds: float, high_seconds: float) -> tuple[int, int]:
    high_seconds = max(0.0, high_seconds)
    low_seconds = max(0.0, min(low_seconds, high_seconds))
    reference = max(low_seconds, high_seconds)
    granularity = 5 if reference < 60 else 15 if reference < 600 else 60
    low = int(math.floor(low_seconds / granularity) * granularity)
    high = int(math.ceil(high_seconds / granularity) * granularity)
    if high_seconds > 0:
        high = max(granularity, high)
    return low, max(low, high)


def unavailable_eta(reason: str, sample_size: int = 0) -> dict:
    return {
        "available": False,
        "approximate": True,
        "source": "none",
        "reason": reason,
        "sampleSize": sample_size,
    }


def estimate_eta(
    *,
    duration_seconds: float | None,
    historical_rtfs,
    transcription_elapsed_seconds: float = 0,
    processed_audio_seconds: float | None = None,
) -> dict:
    """Return a coarse remaining-time range without inventing progress."""
    duration = float(duration_seconds or 0)
    if not math.isfinite(duration) or duration <= 0:
        return unavailable_eta("audio_duration_unknown")

    samples = _valid_numbers(historical_rtfs)
    elapsed = max(0.0, float(transcription_elapsed_seconds or 0))
    processed = float(processed_audio_seconds or 0)

    if math.isfinite(processed) and 0 < processed < duration and elapsed > 0:
        current_rtf = elapsed / processed
        fraction = min(1.0, processed / duration)
        if samples:
            historical_median = statistics.median(samples)
            live_weight = min(0.8, max(0.2, fraction))
            smoothed_rtf = historical_median * (1 - live_weight) + current_rtf * live_weight
        else:
            smoothed_rtf = current_rtf
        uncertainty = max(0.15, 0.55 * (1 - fraction))
        remaining_audio = max(0.0, duration - processed)
        low, high = _rounded_range(
            remaining_audio * smoothed_rtf * (1 - uncertainty),
            remaining_audio * smoothed_rtf * (1 + uncertainty),
        )
        return {
            "available": True,
            "approximate": True,
            "source": "live",
            "minSeconds": low,
            "maxSeconds": high,
            "sampleSize": len(samples),
            "basisRtf": round(smoothed_rtf, 4),
        }

    if not samples:
        return unavailable_eta("insufficient_history")

    median = statistics.median(samples)
    if len(samples) == 1:
        margin = 0.65
    elif len(samples) == 2:
        margin = 0.45
    else:
        margin = max(0.2, 0.4 / math.sqrt(len(samples)))
    low_rtf = max(0.01, min(min(samples) * 0.9, median * (1 - margin)))
    high_rtf = max(max(samples) * 1.1, median * (1 + margin))
    low, high = _rounded_range(
        max(0.0, duration * low_rtf - elapsed),
        max(5.0, duration * high_rtf - elapsed),
    )
    return {
        "available": True,
        "approximate": True,
        "source": "history",
        "minSeconds": low,
        "maxSeconds": high,
        "sampleSize": len(samples),
    }


__all__ = ["estimate_eta", "unavailable_eta"]
