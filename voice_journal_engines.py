"""Optional transcription-engine adapters for the voice journal.

The existing openai-whisper path intentionally remains in ``voice_journal.py``.
This module only describes/validates the additive faster-whisper integration.
"""

from __future__ import annotations

import importlib.metadata
import json
import math
from pathlib import Path


OPENAI_ENGINE = "openai-whisper"
FASTER_ENGINE = "faster-whisper"
DEFAULT_ENGINE = OPENAI_ENGINE
SUPPORTED_ENGINES = (OPENAI_ENGINE, FASTER_ENGINE)
FASTER_MODELS = ("tiny", "base", "small", "medium", "large-v2", "large-v3", "turbo")
FASTER_COMPUTE_TYPES = ("auto", "float16", "float32", "int8", "int8_float16")


FASTER_OPTION_SPECS = {
    "temperature": {"type": "temperature", "default": 0.0, "label": "Temperatura", "tooltip": "Steruje losowością dekodowania."},
    "beam_size": {"type": "integer", "min": 1, "max": 20, "default": 5, "label": "Beam size", "tooltip": "Liczba wiązek dekodowania; większa wartość zwykle działa wolniej."},
    "best_of": {"type": "integer", "min": 1, "max": 20, "default": 5, "label": "Best of", "tooltip": "Liczba kandydatów używana przy temperaturze większej od zera."},
    "vad_filter": {"type": "boolean", "default": False, "label": "Filtr VAD", "tooltip": "Pomija fragmenty uznane za ciszę przez Silero VAD."},
    "vad_threshold": {"type": "number", "min": 0, "max": 1, "default": 0.5, "label": "Próg VAD", "tooltip": "Próg prawdopodobieństwa mowy; działa tylko z filtrem VAD.", "requires": "vad_filter"},
    "vad_min_silence_duration_ms": {"type": "integer", "min": 0, "max": 10000, "default": 2000, "label": "Minimalna cisza VAD (ms)", "tooltip": "Minimalna cisza rozdzielająca fragmenty mowy.", "requires": "vad_filter"},
    "vad_min_speech_duration_ms": {"type": "integer", "min": 0, "max": 10000, "default": 0, "label": "Minimalna mowa VAD (ms)", "tooltip": "Krótsze fragmenty mowy zostaną pominięte.", "requires": "vad_filter"},
    "vad_speech_pad_ms": {"type": "integer", "min": 0, "max": 5000, "default": 400, "label": "Margines VAD (ms)", "tooltip": "Margines dodawany przed i po fragmencie mowy.", "requires": "vad_filter"},
    "condition_on_previous_text": {"type": "boolean", "default": True, "label": "Kontekst poprzedniego tekstu", "tooltip": "Używa poprzedniego segmentu jako kontekstu."},
    "word_timestamps": {"type": "boolean", "default": True, "label": "Timestampy słów", "tooltip": "Zapisuje czasy i confidence poszczególnych słów."},
}


FASTER_PRESETS = {
    "fast": {"temperature": 0.0, "beam_size": 1, "best_of": 1, "vad_filter": True, "word_timestamps": False, "condition_on_previous_text": False},
    "balanced": {name: spec["default"] for name, spec in FASTER_OPTION_SPECS.items()},
    "quality": {"temperature": 0.0, "beam_size": 5, "best_of": 5, "vad_filter": False, "word_timestamps": True, "condition_on_previous_text": True},
}


def normalize_engine(value: str | None) -> str:
    engine = str(value or DEFAULT_ENGINE).strip().lower()
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"Unsupported transcription engine: {engine}")
    return engine


def faster_whisper_health() -> dict:
    try:
        import faster_whisper  # noqa: F401
        from faster_whisper.utils import available_models

        version = importlib.metadata.version("faster-whisper")
        library_models = set(available_models())
        supported_models = [model for model in FASTER_MODELS if model in library_models]
        available = True
        error = None
    except Exception as exc:
        version = None
        supported_models = []
        available = False
        error = f"Faster-Whisper is not installed or cannot be imported: {exc}"
    return {
        "id": FASTER_ENGINE,
        "label": "Faster-Whisper",
        "available": available,
        "version": version,
        "error": error,
        "supportedModels": supported_models,
        "cachedModels": faster_cached_models() if available else [],
        "recommendedModel": "small",
        "supportedLanguages": ["auto", "pl"],
        "supportedTasks": ["transcribe", "translate"],
        "computeTypes": list(FASTER_COMPUTE_TYPES),
        "transcriptionOptions": {
            "supported": list(FASTER_OPTION_SPECS),
            "specs": FASTER_OPTION_SPECS,
            "presets": FASTER_PRESETS,
            "recommendedPreset": "balanced",
        },
    }


def faster_cached_models() -> list[str]:
    """Best-effort Hugging Face cache discovery; never claims an uncached model."""
    roots = [Path.home() / ".cache" / "huggingface" / "hub"]
    cached = []
    for model in FASTER_MODELS:
        directory_name = f"models--Systran--faster-whisper-{model}"
        if any((root / directory_name / "snapshots").is_dir() for root in roots):
            cached.append(model)
    return cached


def _number(name: str, value, spec: dict, *, integer: bool = False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < spec["min"] or number > spec["max"]:
        raise ValueError(f"{name} must be between {spec['min']} and {spec['max']}")
    if integer and not number.is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(number) if integer else number


def validate_faster_options(raw, *, device: str, compute_type: str | None = None) -> tuple[dict, str]:
    if not isinstance(raw, dict):
        raise ValueError("options must be a JSON object")
    unknown = sorted(set(raw) - set(FASTER_OPTION_SPECS))
    if unknown:
        raise ValueError(f"Unsupported Faster-Whisper options: {', '.join(unknown)}")
    selected_compute = str(compute_type or "auto").strip().lower()
    if selected_compute not in FASTER_COMPUTE_TYPES:
        raise ValueError("Unsupported Faster-Whisper compute_type")
    if device == "cpu" and selected_compute in {"float16", "int8_float16"}:
        raise ValueError(f"compute_type {selected_compute} requires CUDA")

    effective = {}
    for name, spec in FASTER_OPTION_SPECS.items():
        value = raw.get(name, spec["default"])
        option_type = spec["type"]
        if option_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be true or false")
            effective[name] = value
        elif option_type == "integer":
            effective[name] = _number(name, value, spec, integer=True)
        elif option_type == "number":
            effective[name] = _number(name, value, spec)
        elif option_type == "temperature":
            values = value if isinstance(value, list) else [value]
            if not values or len(values) > 10:
                raise ValueError("temperature must contain between 1 and 10 values")
            normalized = []
            for item in values:
                if isinstance(item, bool) or not isinstance(item, (int, float)) or not 0 <= float(item) <= 1:
                    raise ValueError("temperature values must be between 0 and 1")
                normalized.append(float(item))
            effective[name] = normalized if isinstance(value, list) else normalized[0]

    if not effective["vad_filter"]:
        for name, spec in FASTER_OPTION_SPECS.items():
            if spec.get("requires") == "vad_filter":
                effective.pop(name, None)
    if effective["temperature"] == 0:
        # best_of has no effect with beam search; omit it instead of failing.
        effective.pop("best_of", None)
    return effective, selected_compute


def faster_worker_options(options: dict) -> dict:
    """Translate UI-friendly flattened VAD fields to Faster-Whisper's API."""
    payload = dict(options)
    vad_parameters = {}
    mapping = {
        "vad_threshold": "threshold",
        "vad_min_silence_duration_ms": "min_silence_duration_ms",
        "vad_min_speech_duration_ms": "min_speech_duration_ms",
        "vad_speech_pad_ms": "speech_pad_ms",
    }
    for source, target in mapping.items():
        if source in payload:
            vad_parameters[target] = payload.pop(source)
    if payload.get("vad_filter") and vad_parameters:
        payload["vad_parameters"] = vad_parameters
    return payload


__all__ = [
    "DEFAULT_ENGINE", "FASTER_COMPUTE_TYPES", "FASTER_ENGINE", "FASTER_MODELS",
    "OPENAI_ENGINE", "SUPPORTED_ENGINES", "faster_whisper_health",
    "faster_worker_options", "normalize_engine", "validate_faster_options",
]
