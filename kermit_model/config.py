"""Trusted local process configuration. No request-supplied provider endpoints."""

from dataclasses import dataclass
import os
from urllib.parse import urlsplit


PROFILES = ("quick", "normal", "deep", "max")
REASONING = {"quick": "low", "normal": "medium", "deep": "high", "max": "high"}
MAX_OUTPUT = {"quick": 512, "normal": 768, "deep": 1200, "max": 1600}
EVIDENCE_LIMIT = {"quick": 4, "normal": 6, "deep": 8, "max": 12}
THINK_OPTION = {"qwen3.5:4b": False}


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    base_url: str
    model: str
    profile: str
    reasoning: str
    max_output_tokens: int
    keep_alive: str
    think: bool | None = None
    temperature: float = 0.0
    evidence_limit: int = 12
    workload_class: str = "interactive"


def configured(profile="normal", provider=None, environ=None, *, workload_class="interactive"):
    env = os.environ if environ is None else environ
    if workload_class != "interactive":
        raise ValueError("unsupported workload class")
    if profile not in PROFILES:
        raise ValueError("unsupported reasoning profile")
    selected = provider or env.get("KERMIT_LLM_PROVIDER", "fake")
    if selected not in ("fake", "ollama"):
        raise ValueError("unsupported local provider")
    model = env.get("KERMIT_LLM_MODEL_" + profile.upper()) or env.get("KERMIT_LLM_MODEL", "qwen3.5:4b")
    if not model or len(model) > 120 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/-" for c in model):
        raise ValueError("invalid configured model tag")
    base = env.get("KERMIT_LLM_BASE_URL", "http://127.0.0.1:11434")
    parsed = urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment or not parsed.port:
        raise ValueError("invalid configured Ollama endpoint")
    keep_alive = env.get("KERMIT_LLM_KEEP_ALIVE", "2m")
    if not keep_alive or len(keep_alive) > 12 or not keep_alive[:-1].isdigit() or keep_alive[-1] not in "smh":
        raise ValueError("invalid configured keep-alive")
    output = int(env.get("KERMIT_LLM_OUTPUT_TOKENS_" + profile.upper(), MAX_OUTPUT[profile]))
    limit = int(env.get("KERMIT_LLM_EVIDENCE_LIMIT_" + profile.upper(), EVIDENCE_LIMIT[profile]))
    if not 128 <= output <= 2048 or not 1 <= limit <= 12:
        raise ValueError("invalid configured generation budget")
    return ModelConfig(selected, base.rstrip("/"), model, profile, REASONING[profile], output,
                       keep_alive, THINK_OPTION.get(model), 0.0, limit)
