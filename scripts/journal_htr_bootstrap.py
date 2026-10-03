"""Zero-touch bootstrap for the dashboard's local eScriptorium HTR service.

The script is intentionally idempotent. It is called by start-dev.cmd and:
* creates private local configuration without printing secrets;
* starts and migrates the pinned eScriptorium stack;
* provisions a local administrator, API token, project, and starter HTR model;
* writes the resulting non-interactive dashboard configuration.

If firmware virtualization is disabled, local uploads remain enabled and the
script exits quickly with a precise diagnostic. Re-running start-dev.cmd after
virtualization is enabled completes the remaining steps.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTR_DIR = ROOT / "htr"
PRIVATE_ENV = HTR_DIR / "variables.env"
DASHBOARD_ENV = ROOT / ".env.development"
STATE_PATH = HTR_DIR / "bootstrap-state.json"
COMPOSE_PATH = ROOT / "docker-compose.htr.yml"
BASE_URL = "http://127.0.0.1:8081"
PROJECT_NAME = "Journal HTR"
MODEL_NAME = "Startowy model pisma CE (Bohemica)"
MODEL_RECORD_API = "https://zenodo.org/api/records/11673242"
MODEL_FILENAME = "rec_bohemica.mlmodel"


def log(message: str) -> None:
    print(f"[journal-htr] {message}", flush=True)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def upsert_env(path: Path, updates: dict[str, str], heading: str | None = None) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    indexes: dict[str, int] = {}
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            indexes[line.split("=", 1)[0].strip()] = index
    missing: list[tuple[str, str]] = []
    for key, value in updates.items():
        rendered = f"{key}={value}"
        if key in indexes:
            lines[indexes[key]] = rendered
        else:
            missing.append((key, rendered))
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        if heading:
            lines.append(f"# {heading}")
        lines.extend(rendered for _, rendered in missing)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def configure_private_files() -> dict[str, str]:
    HTR_DIR.mkdir(parents=True, exist_ok=True)
    existing = parse_env(PRIVATE_ENV)
    private_updates = {
        "DOMAIN": "localhost",
        "SECRET_KEY": existing.get("SECRET_KEY") or secrets.token_urlsafe(64),
        "CSRF_TRUSTED_ORIGINS": f"{BASE_URL},http://localhost:8081",
        "SITE_NAME": "Local Journal HTR",
        "REDIS_HOST": "redis",
        "SQL_HOST": "db",
        "SQL_PORT": "5432",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": existing.get("POSTGRES_PASSWORD")
        or secrets.token_urlsafe(32),
        "POSTGRES_DB": "escriptorium",
        "DJANGO_SU_NAME": existing.get("DJANGO_SU_NAME") or "journal-admin",
        "DJANGO_SU_EMAIL": "journal@localhost.invalid",
        "DJANGO_SU_PASSWORD": existing.get("DJANGO_SU_PASSWORD")
        or secrets.token_urlsafe(32),
        "DJANGO_FROM_EMAIL": "journal@localhost.invalid",
        "KRAKEN_TRAINING_LOAD_THREADS": "4",
        "KRAKEN_TRAINING_BATCH_SIZE": "1",
        "ESCRIPTORIUM_HOST_PORT": "8081",
    }
    upsert_env(PRIVATE_ENV, private_updates)
    dashboard_existing = parse_env(DASHBOARD_ENV)
    dashboard_updates = {
        "HTR_ENABLED": "true",
        "HTR_PROVIDER": "escriptorium",
        "ESCRIPTORIUM_BASE_URL": BASE_URL,
        "ESCRIPTORIUM_API_TOKEN": dashboard_existing.get(
            "ESCRIPTORIUM_API_TOKEN", ""
        ),
        "ESCRIPTORIUM_PROJECT_SLUG": dashboard_existing.get(
            "ESCRIPTORIUM_PROJECT_SLUG", "journal-htr"
        ),
        "ESCRIPTORIUM_MAIN_SCRIPT": "Latin",
        "HTR_MAX_UPLOAD_MB": "50",
        "HTR_TRAINING_MIN_LINES": "200",
        "HTR_RETRAIN_AFTER_NEW_LINES": "300",
    }
    upsert_env(
        DASHBOARD_ENV,
        dashboard_updates,
        "Local Journal OCR/HTR — managed automatically by the bootstrap script.",
    )
    return private_updates


def ensure_dashboard_dependencies() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError:
        log("Instaluję lokalną obsługę obrazów…")
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(ROOT / "requirements-htr.txt"),
            ],
            timeout=900,
        )


def run(
    arguments: list[str],
    *,
    timeout: int = 300,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        arguments,
        cwd=ROOT,
        check=check,
        timeout=timeout,
        text=True,
        capture_output=capture,
    )


def firmware_virtualization_enabled() -> bool | None:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "(Get-CimInstance Win32_Processor | "
        "Select-Object -First 1 -ExpandProperty VirtualizationFirmwareEnabled)",
    ]
    try:
        result = run(command, timeout=10, check=False, capture=True)
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip().lower()
    if value in {"true", "false"}:
        return value == "true"
    return None


def docker_ready() -> bool:
    try:
        result = run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            timeout=8,
            check=False,
            capture=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def start_docker_desktop() -> None:
    executable = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / (
        "Docker/Docker/Docker Desktop.exe"
    )
    if not executable.exists():
        return
    subprocess.Popen(
        [str(executable)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def ensure_docker() -> bool:
    virtualization = firmware_virtualization_enabled()
    if virtualization is False:
        write_state(
            "waiting_for_virtualization",
            "Wirtualizacja procesora jest wyłączona w UEFI/BIOS.",
        )
        log(
            "Upload lokalny jest gotowy. OCR oczekuje na włączenie AMD-V/SVM "
            "w UEFI/BIOS; konfiguracja i sekrety są już przygotowane."
        )
        return False
    if docker_ready():
        return True
    start_docker_desktop()
    log("Uruchamiam Docker Desktop…")
    for _ in range(30):
        if docker_ready():
            return True
        time.sleep(2)
    write_state("docker_unavailable", "Docker Desktop nie uruchomił silnika Linux.")
    log("Docker Desktop nie uruchomił silnika Linux; upload lokalny pozostaje dostępny.")
    return False


def compose(
    *arguments: str,
    timeout: int = 900,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    return run(
        ["docker", "compose", "-f", str(COMPOSE_PATH), *arguments],
        timeout=timeout,
        check=check,
        capture=capture,
    )


def http_json(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    token: str | None = None,
    timeout: int = 30,
) -> object:
    data = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Token {token}"
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}


def wait_for_database(private: dict[str, str], timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = compose(
            "exec",
            "-T",
            "db",
            "pg_isready",
            "-U",
            private["POSTGRES_USER"],
            "-d",
            private["POSTGRES_DB"],
            timeout=10,
            check=False,
            capture=True,
        )
        if result.returncode == 0:
            log("PostgreSQL jest gotowy.")
            return
        time.sleep(2)
    raise RuntimeError("PostgreSQL did not become ready")


def migrate_database() -> None:
    compose(
        "run",
        "--rm",
        "web",
        "python",
        "manage.py",
        "migrate",
        "--noinput",
        timeout=1800,
    )
    compose(
        "run",
        "--rm",
        "web",
        "python",
        "manage.py",
        "migrate",
        "--check",
        timeout=300,
    )
    log("Migracje eScriptorium są gotowe.")


def wait_for_web_backend(timeout: int = 120) -> None:
    probe = (
        "import socket;"
        "s=socket.create_connection(('127.0.0.1',8000),5);"
        "s.close()"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = compose(
            "exec",
            "-T",
            "web",
            "python",
            "-c",
            probe,
            timeout=10,
            check=False,
            capture=True,
        )
        if result.returncode == 0:
            log("Backend web eScriptorium jest gotowy.")
            return
        time.sleep(2)
    raise RuntimeError("eScriptorium web backend did not become ready")


def http_status(path: str, timeout: int = 5) -> int | None:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def wait_for_nginx(timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = http_status("/")
        if status is not None and 200 <= status < 500:
            log(f"Nginx eScriptorium jest gotowy (HTTP {status}).")
            return
        time.sleep(2)
    raise RuntimeError("eScriptorium nginx did not become ready")


def wait_for_api_http(timeout: int = 120) -> None:
    """Wait for the API route without requiring credentials to exist yet.

    eScriptorium protects /api/. HTTP 401 proves that nginx reached Django and
    that authentication middleware is serving requests, so it is a successful
    readiness result before the bootstrap has provisioned its token.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = http_status("/api/")
        if status in {200, 401, 403}:
            log(f"API eScriptorium jest gotowe (HTTP {status}).")
            return
        time.sleep(2)
    raise RuntimeError("eScriptorium API route did not become ready")


def wait_for_authenticated_api(token: str, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            http_json("GET", "/api/", token=token, timeout=5)
            log("Uwierzytelnione API eScriptorium odpowiada.")
            return
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            time.sleep(2)
    raise RuntimeError("Authenticated eScriptorium API did not become ready")


def provision_user(private: dict[str, str]) -> None:
    code = (
        "import os;"
        "from django.contrib.auth import get_user_model;"
        "U=get_user_model();"
        "u,_=U.objects.get_or_create(username=os.environ['DJANGO_SU_NAME']);"
        "u.email=os.environ['DJANGO_SU_EMAIL'];"
        "u.is_staff=True;u.is_superuser=True;"
        "u.set_password(os.environ['DJANGO_SU_PASSWORD']);u.save()"
    )
    compose("exec", "-T", "web", "python", "manage.py", "shell", "-c", code)


def get_token(private: dict[str, str]) -> str:
    result = http_json(
        "POST",
        "/api/token-auth/",
        payload={
            "username": private["DJANGO_SU_NAME"],
            "password": private["DJANGO_SU_PASSWORD"],
        },
    )
    token = str(result.get("token") or "") if isinstance(result, dict) else ""
    if not token:
        raise RuntimeError("eScriptorium did not return an API token")
    return token


def items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    return []


def ensure_project(token: str) -> dict:
    projects = items(http_json("GET", "/api/projects/", token=token))
    existing = next((item for item in projects if item.get("name") == PROJECT_NAME), None)
    created_now = existing is None
    if existing is None:
        created = http_json(
            "POST", "/api/projects/", payload={"name": PROJECT_NAME}, token=token
        )
        existing = created if isinstance(created, dict) else {}
    slug = str(existing.get("slug") or "")
    if not slug:
        raise RuntimeError("eScriptorium project has no slug")
    return {
        "name": PROJECT_NAME,
        "slug": slug,
        "id": existing.get("pk") or existing.get("id"),
        "status": "created" if created_now else "existing",
    }


def download_starter_model() -> Path:
    model_dir = HTR_DIR / "bootstrap"
    model_dir.mkdir(parents=True, exist_ok=True)
    destination = model_dir / MODEL_FILENAME
    if destination.exists() and destination.stat().st_size > 1_000_000:
        return destination
    request = urllib.request.Request(
        MODEL_RECORD_API, headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        record = json.load(response)
    files = record.get("files") or []
    model = next((item for item in files if item.get("key") == MODEL_FILENAME), None)
    if not model:
        raise RuntimeError("Starter model is missing from its pinned Zenodo record")
    url = model.get("links", {}).get("content") or model.get("links", {}).get("self")
    if not url:
        raise RuntimeError("Starter model download URL is missing")
    temporary = destination.with_suffix(".download")
    log("Pobieram startowy model pisma (jednorazowo, około 17 MB)…")
    with urllib.request.urlopen(url, timeout=180) as response:
        temporary.write_bytes(response.read())
    expected_size = int(model.get("size") or 0)
    if expected_size and temporary.stat().st_size != expected_size:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Starter model download is incomplete")
    temporary.replace(destination)
    return destination


def multipart(fields: dict[str, str], field_name: str, path: Path) -> tuple[bytes, str]:
    boundary = f"----journal-htr-bootstrap-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{path.name}"\r\n'
            ).encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def ensure_starter_model(token: str) -> dict:
    models = items(http_json("GET", "/api/models/", token=token))
    existing = next((item for item in models if item.get("name") == MODEL_NAME), None)
    if existing:
        return {
            "name": MODEL_NAME,
            "id": existing.get("pk") or existing.get("id"),
            "status": "existing",
        }
    model_path = download_starter_model()
    body, content_type = multipart(
        {"name": MODEL_NAME, "job": "Recognize"}, "file", model_path
    )
    request = urllib.request.Request(
        f"{BASE_URL}/api/models/",
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": f"Token {token}",
            "Content-Type": content_type,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read()
            created = json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Starter model import failed (HTTP {exc.code}): {detail}"
        ) from exc
    return {
        "name": MODEL_NAME,
        "id": created.get("pk") or created.get("id"),
        "status": "imported",
    }


def write_state(status: str, detail: str = "") -> None:
    STATE_PATH.write_text(
        json.dumps(
            {
                "status": status,
                "detail": detail,
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def ready_configuration() -> tuple[bool, dict]:
    dashboard = parse_env(DASHBOARD_ENV)
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    ready = bool(
        state.get("status") == "ready"
        and dashboard.get("ESCRIPTORIUM_API_TOKEN")
        and dashboard.get("ESCRIPTORIUM_PROJECT_SLUG")
    )
    return ready, state


def start_stack() -> int:
    private = configure_private_files()
    ensure_dashboard_dependencies()
    log("Konfiguracja prywatna gotowa; nie trzeba edytować .env.")
    if not ensure_docker():
        return 1
    try:
        configured, previous_state = ready_configuration()
        if configured:
            log("Uruchamiam zapisany stos eScriptorium/Kraken…")
            compose("up", "-d", timeout=1800)
            wait_for_database(private)
            wait_for_web_backend()
            wait_for_nginx()
            wait_for_api_http()
            token = parse_env(DASHBOARD_ENV).get("ESCRIPTORIUM_API_TOKEN", "")
            wait_for_authenticated_api(token)
            write_state("ready", str(previous_state.get("detail") or ""))
            log("Serwer OCR jest gotowy.")
            return 0

        log("Uruchamiam lokalny eScriptorium/Kraken…")
        compose("up", "-d", "db", "redis", timeout=1800)
        wait_for_database(private)
        migrate_database()
        compose("up", "-d", timeout=1800)
        wait_for_web_backend()
        wait_for_nginx()
        wait_for_api_http()
        provision_user(private)
        token = get_token(private)
        wait_for_authenticated_api(token)
        project = ensure_project(token)
        model = ensure_starter_model(token)
        upsert_env(
            DASHBOARD_ENV,
            {
                "HTR_ENABLED": "true",
                "HTR_PROVIDER": "escriptorium",
                "ESCRIPTORIUM_BASE_URL": BASE_URL,
                "ESCRIPTORIUM_API_TOKEN": token,
                "ESCRIPTORIUM_PROJECT_SLUG": project["slug"],
                "ESCRIPTORIUM_MAIN_SCRIPT": "Latin",
            },
        )
        write_state(
            "ready",
            json.dumps(
                {
                    "project": project,
                    "starterModel": model,
                    "authenticatedApi": True,
                },
                ensure_ascii=False,
            ),
        )
        log("Gotowe: upload, segmentacja i transkrypcja są skonfigurowane.")
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, urllib.error.URLError) as exc:
        write_state("error", str(exc)[:500])
        log(f"Nie udało się dokończyć OCR: {exc}")
        return 1


def stop_stack() -> int:
    if not docker_ready():
        log("Docker nie działa; serwer OCR jest już zatrzymany.")
        return 0
    try:
        log("Zatrzymuję eScriptorium/Kraken bez usuwania danych…")
        compose("stop", timeout=600)
        log("Serwer OCR został zatrzymany.")
        return 0
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"Nie udało się zatrzymać OCR: {exc}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--start", action="store_true")
    actions.add_argument("--stop", action="store_true")
    arguments = parser.parse_args()
    if arguments.stop:
        return stop_stack()
    return start_stack()


if __name__ == "__main__":
    raise SystemExit(main())
