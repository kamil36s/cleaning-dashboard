"""Whitelisted openai-whisper transcription options and validation."""

from __future__ import annotations

import inspect
import math


class TranscriptionOptionsError(ValueError):
    pass


OPTION_SPECS = {
    "temperature": {
        "type": "temperature",
        "default": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        "label": "Temperatura",
        "tooltip": "Steruje losowością; lista wartości uruchamia kolejne próby awaryjne.",
    },
    "beam_size": {"type": "integer", "min": 1, "max": 20, "default": None, "label": "Beam size", "tooltip": "Liczba wiązek dla temperatury 0; więcej zwykle działa wolniej."},
    "best_of": {"type": "integer", "min": 1, "max": 20, "default": None, "label": "Best of", "tooltip": "Liczba prób przy temperaturze większej od 0."},
    "patience": {"type": "number", "min": 0.1, "max": 10, "default": None, "label": "Patience", "tooltip": "Rozszerza wyszukiwanie beam; wymaga ustawionego beam size."},
    "length_penalty": {"type": "number", "min": 0, "max": 1, "default": None, "label": "Length penalty", "tooltip": "Koryguje preferowaną długość wyniku w zakresie 0–1."},
    "condition_on_previous_text": {"type": "boolean", "default": True, "label": "Kontekst poprzedniego tekstu", "tooltip": "Podaje poprzedni fragment jako kontekst następnego okna."},
    "initial_prompt": {"type": "string", "maxLength": 2000, "default": None, "label": "Prompt początkowy", "tooltip": "Pomaga zasugerować nazwy własne, słownictwo i kontekst nagrania."},
    "no_speech_threshold": {"type": "number", "min": 0, "max": 1, "default": 0.6, "label": "Próg ciszy", "tooltip": "Próg uznania fragmentu za ciszę, używany razem z logprob threshold."},
    "logprob_threshold": {"type": "number", "min": -20, "max": 0, "default": -1.0, "label": "Próg log probability", "tooltip": "Słabszy średni logprob uruchamia próbę awaryjną."},
    "compression_ratio_threshold": {"type": "number", "min": 0.1, "max": 10, "default": 2.4, "label": "Próg kompresji", "tooltip": "Wysoka powtarzalność tekstu uruchamia próbę awaryjną."},
    "suppress_tokens": {"type": "tokens", "maxLength": 500, "default": "-1", "label": "Tłumione tokeny", "tooltip": "Lista identyfikatorów tokenów oddzielonych przecinkami; -1 używa listy Whispera."},
    "word_timestamps": {"type": "boolean", "default": True, "label": "Timestampy słów", "tooltip": "Wyznacza znaczniki czasu i confidence poszczególnych słów; może spowolnić analizę."},
    "fp16": {"type": "boolean", "default": True, "label": "FP16", "tooltip": "Obliczenia półprecyzyjne; efektywnie dostępne tylko na CUDA."},
}


def _base_options():
    return {name: spec["default"] for name, spec in OPTION_SPECS.items()}


TRANSCRIPTION_PRESETS = {
    "fast": {
        **_base_options(),
        "temperature": 0.0,
        "condition_on_previous_text": False,
        "word_timestamps": False,
    },
    "balanced": _base_options(),
    "quality": {
        **_base_options(),
        "temperature": 0.0,
        "beam_size": 5,
        "patience": 1.0,
        "word_timestamps": True,
    },
}


def supported_transcription_option_names(whisper_module) -> list[str]:
    try:
        explicit = set(inspect.signature(whisper_module.transcribe).parameters)
        from whisper.decoding import DecodingOptions

        decoding = set(DecodingOptions.__dataclass_fields__)
    except Exception:
        return []
    return [name for name in OPTION_SPECS if name in explicit or name in decoding]


def transcription_options_capabilities(whisper_module) -> dict:
    supported = supported_transcription_option_names(whisper_module)
    return {
        "supported": supported,
        "specs": {name: OPTION_SPECS[name] for name in supported},
        "presets": {
            name: {key: value for key, value in values.items() if key in supported}
            for name, values in TRANSCRIPTION_PRESETS.items()
        },
        "recommendedPreset": "balanced",
    }


def _number(name: str, value, spec: dict, *, integer: bool = False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TranscriptionOptionsError(f"{name} must be a number or null")
    number = float(value)
    if not math.isfinite(number) or number < spec["min"] or number > spec["max"]:
        raise TranscriptionOptionsError(f"{name} must be between {spec['min']} and {spec['max']}")
    if integer and not number.is_integer():
        raise TranscriptionOptionsError(f"{name} must be an integer")
    return int(number) if integer else number


def _temperature(value):
    values = value if isinstance(value, list) else [value]
    if not values or len(values) > 10:
        raise TranscriptionOptionsError("temperature must contain between 1 and 10 values")
    normalized = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise TranscriptionOptionsError("temperature must be a number or a list of numbers")
        number = float(item)
        if not math.isfinite(number) or not 0 <= number <= 1:
            raise TranscriptionOptionsError("temperature values must be between 0 and 1")
        normalized.append(number)
    return normalized[0] if not isinstance(value, list) else normalized


def _tokens(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 500:
        raise TranscriptionOptionsError("suppress_tokens must be a short comma-separated string or null")
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not part for part in parts) or len(parts) > 100:
        raise TranscriptionOptionsError("suppress_tokens must contain valid token ids")
    try:
        tokens = [int(part) for part in parts]
    except ValueError as exc:
        raise TranscriptionOptionsError("suppress_tokens must contain integers") from exc
    if any(token < -1 or token > 51864 for token in tokens):
        raise TranscriptionOptionsError("suppress_tokens contains an out-of-range token id")
    return ",".join(str(token) for token in tokens)


def validate_transcription_options(raw, *, supported_names, device: str) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise TranscriptionOptionsError("options must be a JSON object")
    supported = set(supported_names)
    unknown = sorted(set(raw) - supported)
    if unknown:
        raise TranscriptionOptionsError(f"Unsupported transcription options: {', '.join(unknown)}")

    effective = {name: OPTION_SPECS[name]["default"] for name in supported_names}
    for name, value in raw.items():
        spec = OPTION_SPECS[name]
        option_type = spec["type"]
        if option_type == "temperature":
            effective[name] = _temperature(value)
        elif option_type == "integer":
            effective[name] = _number(name, value, spec, integer=True)
        elif option_type == "number":
            effective[name] = _number(name, value, spec)
        elif option_type == "boolean":
            if not isinstance(value, bool):
                raise TranscriptionOptionsError(f"{name} must be true or false")
            effective[name] = value
        elif option_type == "string":
            if value is not None and (not isinstance(value, str) or len(value) > spec["maxLength"]):
                raise TranscriptionOptionsError(f"{name} must be a string up to {spec['maxLength']} characters or null")
            effective[name] = value.strip() or None if isinstance(value, str) else None
        elif option_type == "tokens":
            effective[name] = _tokens(value)

    if effective.get("patience") is not None and effective.get("beam_size") is None:
        raise TranscriptionOptionsError("patience requires beam_size")
    if "fp16" in effective and device != "cuda":
        effective["fp16"] = False
    return effective


__all__ = [
    "OPTION_SPECS",
    "TRANSCRIPTION_PRESETS",
    "TranscriptionOptionsError",
    "supported_transcription_option_names",
    "transcription_options_capabilities",
    "validate_transcription_options",
]
