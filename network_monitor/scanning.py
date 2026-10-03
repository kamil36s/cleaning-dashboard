from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import platform
from pathlib import Path
import re
import socket
import subprocess
import threading
from typing import Optional


IPV4_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
WINDOWS_ARP_RE = re.compile(
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+(?P<mac>[0-9a-fA-F-]{17}|[0-9a-fA-F:]{17})\s+\S+"
)
LINUX_IP_RE = re.compile(
    r"^\d+:\s+(?P<name>[^\s]+)\s+inet\s+(?P<ip>\d{1,3}(?:\.\d{1,3}){3})/(?P<prefix>\d+)"
)
LINUX_NEIGH_RE = re.compile(
    r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3}).*?\slladdr\s+(?P<mac>[0-9a-fA-F:]{17})\s+(?P<state>\S+)"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_mac(value: str | None) -> str | None:
    if not value:
        return None
    normalized = str(value).strip().replace("-", ":").upper()
    if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", normalized):
        return None
    if normalized == "FF:FF:FF:FF:FF:FF":
        return None
    return normalized


def is_valid_netmask(value: str) -> bool:
    try:
        ipaddress.IPv4Network(f"0.0.0.0/{value}")
        return True
    except Exception:
        return False


def is_private_ipv4(value: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(value)
    except Exception:
        return False
    return ip.is_private and not ip.is_loopback and not ip.is_link_local


@dataclass(frozen=True)
class InterfaceNetwork:
    name: str
    ip: str
    netmask: str
    network: str


@dataclass(frozen=True)
class DeviceObservation:
    ip: str
    mac: str | None
    detected_name: str | None
    custom_name: str | None
    custom_category: str | None
    custom_owner: str | None
    is_online: bool
    last_method: str


@dataclass(frozen=True)
class ScanResult:
    started_at: str
    finished_at: str
    networks: list[str]
    observations: list[DeviceObservation]
    errors: list[str]


class BaseSystemAdapter:
    def run(self, args: list[str], timeout: int = 8) -> str:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return proc.stdout or proc.stderr or ""

    def list_local_networks(self) -> list[InterfaceNetwork]:
        raise NotImplementedError

    def read_arp_table(self) -> dict[str, str]:
        raise NotImplementedError

    def ping(self, ip: str, timeout_ms: int = 400) -> bool:
        raise NotImplementedError


class WindowsAdapter(BaseSystemAdapter):
    def list_local_networks(self) -> list[InterfaceNetwork]:
        output = self.run(["ipconfig"], timeout=10)
        interfaces: list[InterfaceNetwork] = []
        seen: set[tuple[str, str]] = set()

        current_name = ""
        current_ip: str | None = None
        current_mask: str | None = None

        def flush() -> None:
            nonlocal current_name, current_ip, current_mask
            if not current_ip or not current_mask:
                current_ip = None
                current_mask = None
                return
            if not is_private_ipv4(current_ip):
                current_ip = None
                current_mask = None
                return
            try:
                network = str(ipaddress.IPv4Network(f"{current_ip}/{current_mask}", strict=False))
            except Exception:
                current_ip = None
                current_mask = None
                return
            key = (current_name or "windows", network)
            if key not in seen:
                seen.add(key)
                interfaces.append(
                    InterfaceNetwork(
                        name=current_name or "windows",
                        ip=current_ip,
                        netmask=current_mask,
                        network=network,
                    )
                )
            current_ip = None
            current_mask = None

        for raw_line in output.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                flush()
                continue
            if not line.startswith(" ") and stripped.endswith(":"):
                flush()
                current_name = stripped.rstrip(":")
                continue
            match = IPV4_RE.search(stripped)
            if not match:
                continue
            candidate = match.group(1)
            if "IPv4" in stripped:
                current_ip = candidate
                continue
            if current_ip and candidate != current_ip and is_valid_netmask(candidate):
                current_mask = candidate

        flush()
        return interfaces

    def read_arp_table(self) -> dict[str, str]:
        output = self.run(["arp", "-a"], timeout=8)
        table: dict[str, str] = {}
        for line in output.splitlines():
            match = WINDOWS_ARP_RE.search(line)
            if not match:
                continue
            ip = match.group("ip")
            mac = normalize_mac(match.group("mac"))
            if not mac or not is_private_ipv4(ip):
                continue
            table[ip] = mac
        return table

    def ping(self, ip: str, timeout_ms: int = 400) -> bool:
        proc = subprocess.run(
            ["ping", "-n", "1", "-w", str(max(100, timeout_ms)), ip],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(3, int(timeout_ms / 1000) + 3),
            check=False,
        )
        return proc.returncode == 0


class LinuxAdapter(BaseSystemAdapter):
    def list_local_networks(self) -> list[InterfaceNetwork]:
        output = self.run(["ip", "-o", "-f", "inet", "addr", "show"], timeout=8)
        interfaces: list[InterfaceNetwork] = []
        seen: set[tuple[str, str]] = set()
        for line in output.splitlines():
            match = LINUX_IP_RE.search(line)
            if not match:
                continue
            ip = match.group("ip")
            prefix = int(match.group("prefix"))
            if not is_private_ipv4(ip):
                continue
            network_obj = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
            key = (match.group("name"), str(network_obj))
            if key in seen:
                continue
            seen.add(key)
            interfaces.append(
                InterfaceNetwork(
                    name=match.group("name"),
                    ip=ip,
                    netmask=str(network_obj.netmask),
                    network=str(network_obj),
                )
            )
        return interfaces

    def read_arp_table(self) -> dict[str, str]:
        table: dict[str, str] = {}
        try:
            output = self.run(["ip", "neigh"], timeout=8)
        except Exception:
            output = ""

        for line in output.splitlines():
            match = LINUX_NEIGH_RE.search(line)
            if not match:
                continue
            state = match.group("state").upper()
            if state in {"FAILED", "INCOMPLETE"}:
                continue
            ip = match.group("ip")
            mac = normalize_mac(match.group("mac"))
            if not mac or not is_private_ipv4(ip):
                continue
            table[ip] = mac

        if table:
            return table

        output = self.run(["arp", "-an"], timeout=8)
        for line in output.splitlines():
            fields = line.split()
            if len(fields) < 4:
                continue
            ip = fields[1].strip("()")
            mac = normalize_mac(fields[3])
            if not mac or not is_private_ipv4(ip):
                continue
            table[ip] = mac
        return table

    def ping(self, ip: str, timeout_ms: int = 400) -> bool:
        timeout_secs = max(1, round(timeout_ms / 1000))
        proc = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout_secs), ip],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(3, timeout_secs + 2),
            check=False,
        )
        return proc.returncode == 0


def detect_adapter() -> BaseSystemAdapter:
    system = platform.system().lower()
    if system == "windows":
        return WindowsAdapter()
    if system == "linux":
        return LinuxAdapter()
    raise RuntimeError(f"Unsupported platform for local network scanning: {platform.system()}")


def normalize_device_category(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    aliases = {
        "unknown": None,
        "nieokreslone": None,
        "personal": "personal",
        "osobiste": "personal",
        "household": "household",
        "domowe": "household",
        "home": "household",
        "iot": "iot",
        "smart-home": "iot",
        "infrastructure": "infrastructure",
        "infra": "infrastructure",
        "router": "infrastructure",
    }
    return aliases.get(raw)


OWNER_ALIASES = {
    "kamil": "Ja",
}


def normalize_owner_label(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return OWNER_ALIASES.get(raw.lower(), raw)


def load_device_profiles(path: Path) -> dict[str, dict[str, str | None]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

    if isinstance(raw, dict) and isinstance(raw.get("devices"), dict):
        raw = raw["devices"]
    if not isinstance(raw, dict):
        return {}

    profiles: dict[str, dict[str, str | None]] = {}
    for mac, payload in raw.items():
        normalized_mac = normalize_mac(str(mac))
        if not normalized_mac:
            continue
        name = ""
        category = None
        owner = ""
        if isinstance(payload, str):
            name = payload.strip()
        elif isinstance(payload, dict):
            name = str(payload.get("name") or "").strip()
            category = normalize_device_category(payload.get("category"))
            owner = normalize_owner_label(payload.get("owner"))
        if name or category or owner:
            profiles[normalized_mac] = {
                "name": name or None,
                "category": category or None,
                "owner": owner or None,
            }
    return profiles


class LanScanner:
    def __init__(
        self,
        names_path: Path,
        scan_interval_seconds: int = 30,
        ping_timeout_ms: int = 400,
        max_hosts_per_network: int = 256,
        max_workers: int = 64,
        adapter: Optional[BaseSystemAdapter] = None,
    ) -> None:
        self.names_path = Path(names_path)
        self.scan_interval_seconds = max(5, int(scan_interval_seconds))
        self.ping_timeout_ms = max(100, int(ping_timeout_ms))
        self.max_hosts_per_network = max(16, int(max_hosts_per_network))
        self.max_workers = max(4, int(max_workers))
        self.adapter = adapter or detect_adapter()
        self._hostname_cache: dict[str, str | None] = {}
        self._hostname_cache_lock = threading.Lock()

    def scan(self) -> ScanResult:
        started_at = utc_now_iso()
        errors: list[str] = []

        try:
            interfaces = self.adapter.list_local_networks()
        except Exception as exc:
            finished_at = utc_now_iso()
            return ScanResult(
                started_at=started_at,
                finished_at=finished_at,
                networks=[],
                observations=[],
                errors=[f"list_local_networks_failed:{exc}"],
            )

        eligible_networks = self._eligible_networks(interfaces)
        networks = [str(net) for net in eligible_networks]
        local_ips = {iface.ip for iface in interfaces}
        targets = self._build_targets(eligible_networks, local_ips)

        if not targets:
            finished_at = utc_now_iso()
            return ScanResult(
                started_at=started_at,
                finished_at=finished_at,
                networks=networks,
                observations=[],
                errors=["no_eligible_targets"],
            )

        ping_results = self._ping_targets(targets, errors)

        try:
            arp_after = self.adapter.read_arp_table()
        except Exception as exc:
            arp_after = {}
            errors.append(f"arp_read_failed:{exc}")

        device_profiles = load_device_profiles(self.names_path)
        observations = self._build_observations(
            eligible_networks=eligible_networks,
            ping_results=ping_results,
            arp_after=arp_after,
            device_profiles=device_profiles,
        )
        finished_at = utc_now_iso()
        return ScanResult(
            started_at=started_at,
            finished_at=finished_at,
            networks=networks,
            observations=observations,
            errors=errors,
        )

    def _eligible_networks(self, interfaces: list[InterfaceNetwork]) -> list[ipaddress.IPv4Network]:
        networks: list[ipaddress.IPv4Network] = []
        seen: set[str] = set()
        for iface in interfaces:
            try:
                network = ipaddress.IPv4Network(iface.network, strict=False)
            except Exception:
                continue
            host_count = max(0, network.num_addresses - 2)
            if not network.is_private:
                continue
            if str(network.network_address).startswith("169.254."):
                continue
            if host_count == 0 or host_count > self.max_hosts_per_network:
                continue
            key = str(network)
            if key in seen:
                continue
            seen.add(key)
            networks.append(network)
        return networks

    def _build_targets(
        self,
        networks: list[ipaddress.IPv4Network],
        local_ips: set[str],
    ) -> list[str]:
        targets: set[str] = set()
        for network in networks:
            for host in network.hosts():
                ip = str(host)
                if ip in local_ips:
                    continue
                targets.add(ip)
        return sorted(targets, key=ipaddress.IPv4Address)

    def _ping_targets(self, targets: list[str], errors: list[str]) -> dict[str, bool]:
        if not targets:
            return {}
        results: dict[str, bool] = {}
        workers = min(self.max_workers, len(targets))
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            future_to_ip = {
                executor.submit(self.adapter.ping, ip, self.ping_timeout_ms): ip for ip in targets
            }
            for future in as_completed(future_to_ip):
                ip = future_to_ip[future]
                try:
                    results[ip] = bool(future.result())
                except Exception as exc:
                    results[ip] = False
                    errors.append(f"ping_failed:{ip}:{exc}")
        return results

    def _build_observations(
        self,
        eligible_networks: list[ipaddress.IPv4Network],
        ping_results: dict[str, bool],
        arp_after: dict[str, str],
        device_profiles: dict[str, dict[str, str | None]],
    ) -> list[DeviceObservation]:
        in_scope = lambda ip: any(ipaddress.IPv4Address(ip) in net for net in eligible_networks)
        observations_by_key: dict[str, DeviceObservation] = {}

        for ip, mac in arp_after.items():
            if not in_scope(ip):
                continue
            method = "scan" if ping_results.get(ip) else "arp"
            observation = self._make_observation(ip=ip, mac=mac, method=method, device_profiles=device_profiles)
            observations_by_key[self._device_key(ip, mac)] = observation

        for ip, ok in ping_results.items():
            if not ok or not in_scope(ip):
                continue
            mac = arp_after.get(ip)
            key = self._device_key(ip, mac)
            if key in observations_by_key:
                continue
            observation = self._make_observation(
                ip=ip,
                mac=mac,
                method="ping" if not mac else "scan",
                device_profiles=device_profiles,
            )
            observations_by_key[key] = observation

        observations = list(observations_by_key.values())
        observations.sort(
            key=lambda item: (
                item.custom_name or item.detected_name or "",
                item.mac or "",
                item.ip,
            )
        )
        return observations

    def _make_observation(
        self,
        ip: str,
        mac: str | None,
        method: str,
        device_profiles: dict[str, dict[str, str | None]],
    ) -> DeviceObservation:
        normalized_mac = normalize_mac(mac)
        profile = device_profiles.get(normalized_mac or "", {})
        detected_name = self._resolve_hostname(ip)
        return DeviceObservation(
            ip=ip,
            mac=normalized_mac,
            detected_name=detected_name or None,
            custom_name=profile.get("name") or None,
            custom_category=profile.get("category") or None,
            custom_owner=profile.get("owner") or None,
            is_online=True,
            last_method=method,
        )

    def _resolve_hostname(self, ip: str) -> str | None:
        with self._hostname_cache_lock:
            if ip in self._hostname_cache:
                return self._hostname_cache[ip]

        default_timeout = socket.getdefaulttimeout()
        resolved: str | None = None
        try:
            socket.setdefaulttimeout(0.35)
            host, _, _ = socket.gethostbyaddr(ip)
            host = host.strip().rstrip(".")
            if host and host != ip:
                resolved = host
        except Exception:
            resolved = None
        finally:
            socket.setdefaulttimeout(default_timeout)

        with self._hostname_cache_lock:
            self._hostname_cache[ip] = resolved
        return resolved

    @staticmethod
    def _device_key(ip: str, mac: str | None) -> str:
        return normalize_mac(mac) or f"ip:{ip}"


class NetworkMonitorService:
    def __init__(self, scanner: LanScanner, store, scan_interval_seconds: int = 30) -> None:
        self.scanner = scanner
        self.store = store
        self.scan_interval_seconds = max(5, int(scan_interval_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            name="network-monitor-scan",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def run_scan_once(self) -> ScanResult:
        result = self.scanner.scan()
        self.store.record_scan(result)
        return result

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_scan_once()
            except Exception:
                pass
            self._stop_event.wait(self.scan_interval_seconds)
