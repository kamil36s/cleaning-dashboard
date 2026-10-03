"""Read-only physical-memory admission for trusted local model calls."""

import ctypes
from dataclasses import dataclass
import json
import os
import sys


MB = 1024 * 1024


@dataclass(frozen=True)
class MemoryObservation:
    total_mb: int
    available_mb: int


@dataclass(frozen=True)
class ResourceProfile:
    model: str
    minimum_available_before_load_mb: int
    recommended_available_before_load_mb: int
    minimum_available_resident_mb: int
    recommended_available_resident_mb: int
    safety_margin_mb: int
    observed_working_set_mb: int | None = None
    observed_private_mb: int | None = None
    observed_peak_private_mb: int | None = None
    sample_count: int = 0
    last_calibrated_at: str | None = None


DEFAULT_PROFILES = {
    "qwen3.5:4b": ResourceProfile("qwen3.5:4b", 5200, 6600, 1200, 2000, 1500,
                                   3700, 4400, 5100),
    "gemma3:4b": ResourceProfile("gemma3:4b", 5500, 7000, 1400, 2300, 1600,
                                  4257, 4619, 4619, 1, "2026-09-29"),
    "phi4-mini:3.8b": ResourceProfile("phi4-mini:3.8b", 5000, 6500, 1400, 2300, 1600,
                                       3403, 3443, 3443, 4, "2026-09-29"),
    "mistral:7b": ResourceProfile("mistral:7b", 6400, 8200, 1700, 2600, 1800,
                                  5300, 5358, 5358, 4, "2026-09-29"),
}
PROFILE_FIELDS = set(ResourceProfile.__dataclass_fields__) - {"model"}
NUMERIC_FIELDS = PROFILE_FIELDS - {"last_calibrated_at"}


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def read_physical_memory():
    """Use GlobalMemoryStatusEx; never inspect processes or invoke a shell."""
    if sys.platform != "win32":
        raise OSError("physical memory observation is only supported on Windows")
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return MemoryObservation(status.ullTotalPhys // MB, status.ullAvailPhys // MB)


def profile_for(model, environ=None):
    """Only trusted process configuration may replace or add a model profile."""
    env = os.environ if environ is None else environ
    raw = env.get("KERMIT_RESOURCE_PROFILES_JSON")
    profiles = DEFAULT_PROFILES
    if raw:
        if len(raw) > 16000:
            raise ValueError("resource profile configuration is too large")
        try:
            overrides = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid resource profile configuration") from exc
        if not isinstance(overrides, dict) or len(overrides) > 32:
            raise ValueError("invalid resource profile configuration")
        profiles = dict(DEFAULT_PROFILES)
        for tag, values in overrides.items():
            if not isinstance(tag, str) or not tag or len(tag) > 120 or not isinstance(values, dict) or not set(values) <= PROFILE_FIELDS:
                raise ValueError("invalid resource profile entry")
            base = vars(profiles[tag]).copy() if tag in profiles else {"model": tag}
            base.update(values)
            try:
                candidate = ResourceProfile(**base)
            except TypeError as exc:
                raise ValueError("incomplete resource profile") from exc
            for field in NUMERIC_FIELDS:
                value = getattr(candidate, field)
                if value is not None and (type(value) is not int or value < 0 or value > 1_000_000):
                    raise ValueError("invalid resource profile measurement")
            if candidate.last_calibrated_at is not None and (not isinstance(candidate.last_calibrated_at, str) or len(candidate.last_calibrated_at) > 40):
                raise ValueError("invalid calibration timestamp")
            if not (0 < candidate.minimum_available_before_load_mb <= candidate.recommended_available_before_load_mb
                    and 0 < candidate.minimum_available_resident_mb <= candidate.recommended_available_resident_mb):
                raise ValueError("invalid resource thresholds")
            profiles[tag] = candidate
    return profiles.get(model)


def preflight(config, provider, *, memory_reader=None, environ=None):
    """Return a bounded, deterministic decision before any model generation."""
    profile = profile_for(config.model, environ)
    health = provider.health(config)
    resident = health.get("state") == "ready" and health.get("modelAvailable") is True
    provider_state = health.get("state") if health.get("state") in ("sleeping", "ready", "unavailable") else "unavailable"
    reader = memory_reader or read_physical_memory
    try:
        memory = reader()
        if not (0 <= memory.available_mb <= memory.total_mb and memory.total_mb > 0):
            raise OSError("invalid physical memory observation")
        available, total = memory.available_mb, memory.total_mb
    except (OSError, AttributeError, TypeError, ValueError):
        available = total = None
    minimum = (profile.minimum_available_resident_mb if resident else profile.minimum_available_before_load_mb) if profile else None
    recommended = (profile.recommended_available_resident_mb if resident else profile.recommended_available_before_load_mb) if profile else None
    state = ("red" if available is None or profile is None or provider_state == "unavailable" or not health.get("modelAvailable")
             else "green" if available >= recommended else "yellow" if available >= minimum else "red")
    deficit_minimum = max(0, minimum - available) if minimum is not None and available is not None else None
    deficit_recommended = max(0, recommended - available) if recommended is not None and available is not None else None
    reason = ("model_unavailable" if provider_state == "unavailable" or not health.get("modelAvailable")
              else "unknown_model" if profile is None else "memory_unavailable" if available is None
              else "below_minimum" if state == "red" else "below_recommended" if state == "yellow" else "sufficient")
    result = {"state": state, "reason": reason, "model": config.model, "providerState": provider_state,
              "modelResident": resident, "totalMb": total, "availableMb": available,
              "utilizationPercent": round(100 * (total - available) / total, 1) if total else None,
              "minimumMb": minimum, "recommendedMb": recommended,
              "deficitToMinimumMb": deficit_minimum, "deficitToRecommendedMb": deficit_recommended,
              "profile": vars(profile).copy() if profile else None}
    result["modelState"] = ("unavailable" if reason in ("model_unavailable", "unknown_model", "memory_unavailable")
                            else "waiting_for_memory" if state == "red" else "resource_pressure" if state == "yellow"
                            else provider_state)
    result["nextGenerationState"] = ("generating" if resident else "loading") if state != "red" else None
    result["message"] = message(result)
    if state == "red":
        result["event"] = {"type": "RESOURCE_GATE_BLOCKED", "model": config.model, "state": state,
                           "availableMb": available, "minimumMb": minimum, "recommendedMb": recommended,
                           "deficitToMinimumMb": deficit_minimum, "deficitToRecommendedMb": deficit_recommended}
    return result


def message(result):
    if result["reason"] == "unknown_model":
        return f"No trusted resource profile is configured for {result['model']}."
    if result["reason"] == "model_unavailable":
        return f"The configured Ollama model {result['model']} is unavailable."
    if result["reason"] == "memory_unavailable":
        return "Available physical memory could not be read; generation is paused."
    available = result["availableMb"] / 1000
    minimum = result["minimumMb"] / 1000
    recommended = result["recommendedMb"] / 1000
    if result["state"] == "red":
        return (f"Kermit needs more available memory before using {result['model']}. "
                f"Available: {result['availableMb']} MiB ({available:.1f} GB). "
                f"Minimum: {result['minimumMb']} MiB ({minimum:.1f} GB). "
                f"Recommended: {result['recommendedMb']} MiB ({recommended:.1f} GB). "
                f"Free at least {result['deficitToMinimumMb']} MiB "
                f"({result['deficitToMinimumMb'] / 1000:.1f} GB) to start; "
                f"about {result['deficitToRecommendedMb']} MiB "
                f"({result['deficitToRecommendedMb'] / 1000:.1f} GB) for comfortable operation.")
    if result["state"] == "yellow":
        return (f"Kermit can probably start, but available memory is below the recommended margin. "
                f"Available: {result['availableMb']} MiB ({available:.1f} GB). "
                f"Minimum: {result['minimumMb']} MiB ({minimum:.1f} GB). "
                f"Recommended: {result['recommendedMb']} MiB ({recommended:.1f} GB). "
                f"Recommended margin: {result['deficitToRecommendedMb']} MiB. Start anyway?")
    return (f"Available memory is sufficient for {result['model']}: "
            f"{result['availableMb']} MiB ({available:.1f} GB) available.")
