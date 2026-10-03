"""Trusted desktop-only service configuration."""

from dataclasses import dataclass
import os
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ServiceConfig:
    host: str = "127.0.0.1"
    port: int = 8767
    origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173",
                                "http://127.0.0.1:8000", "http://localhost:8000")
    provider: str = "ollama"
    profiles: tuple[str, ...] = ("quick", "normal")


def configured(environ=None):
    env = os.environ if environ is None else environ
    host = env.get("KERMIT_SERVICE_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("Kermit service must bind to loopback")
    port = int(env.get("KERMIT_SERVICE_PORT", "8767"))
    if not 1024 <= port <= 65535:
        raise ValueError("invalid Kermit service port")
    origins = tuple(part.strip() for part in env.get(
        "KERMIT_SERVICE_ORIGINS", ",".join(ServiceConfig.origins)).split(","))
    if not origins or len(origins) > 16:
        raise ValueError("invalid Kermit origins")
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost")
                or not parsed.port or parsed.path or parsed.query or parsed.fragment
                or parsed.username or parsed.password or origin != f"http://{parsed.hostname}:{parsed.port}"):
            raise ValueError("Kermit origins must be exact loopback HTTP origins")
    provider = env.get("KERMIT_SERVICE_PROVIDER", "ollama")
    if provider not in ("ollama", "fake"):
        raise ValueError("unsupported Kermit provider")
    return ServiceConfig(host, port, origins, provider)
