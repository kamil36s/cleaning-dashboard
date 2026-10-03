"""Provider boundary: prompt messages in, bounded text out; no tool field."""

from dataclasses import dataclass
from typing import Protocol


class ProviderFailure(Exception):
    def __init__(self, message, category="provider_failure"):
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class ModelResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    finish_reason: str
    usage: dict


class Provider(Protocol):
    def generate(self, messages: tuple, config) -> ModelResult: ...
    def health(self, config) -> dict: ...
