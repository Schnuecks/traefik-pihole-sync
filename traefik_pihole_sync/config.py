"""Configuration from environment variables."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from .records import CNAME, A

DEFAULT_STATE_FILE = "/data/state.json"
# Inside the container /tmp belongs to the app user only.
DEFAULT_HEALTH_FILE = "/tmp/traefik-pihole-sync.health"  # nosec B108

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PiholeConfig:
    url: str
    password: str = field(default="", repr=False)


@dataclass(frozen=True)
class Config:
    traefik_url: str
    piholes: tuple[PiholeConfig, ...]
    record_type: str = A
    target_ip: str | None = None
    target_ipv6: str | None = None
    cname_target: str | None = None
    domains: tuple[str, ...] = ()
    include_apex: bool = False
    tcp_routers: bool = False
    verify_tls: bool | str = True
    interval: int = 60
    delete_threshold: int = 3
    dry_run: bool = False
    state_file: str = DEFAULT_STATE_FILE
    health_file: str = DEFAULT_HEALTH_FILE
    health_max_age: int = 300
    heartbeat: int = 3600
    write_delay: float = 0.5
    max_retries: int = 5
    request_timeout: int = 10
    log_level: str = "INFO"


def parse_bool(name: str, value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false, got {value!r}")


def parse_int(name: str, value: str | None, default: int, minimum: int = 0) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        result = int(value)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from None
    if result < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {result}")
    return result


def parse_float(name: str, value: str | None, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        result = float(value)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {value!r}") from None
    if result < 0:
        raise ConfigError(f"{name} must be >= 0, got {result}")
    return result


def parse_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_verify_tls(value: str | None) -> bool | str:
    """``true``/``false`` or the path of a CA bundle."""
    if value is None or value.strip() == "":
        return True
    v = value.strip()
    if v.lower() in _TRUE:
        return True
    if v.lower() in _FALSE:
        return False
    if not os.path.isfile(v):
        raise ConfigError(f"PIHOLE_VERIFY_TLS: CA file not found: {v}")
    return v


def _read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        raise ConfigError(f"cannot read password file {path}: {e.strerror}") from None


def resolve_passwords(env: Mapping[str, str], count: int) -> list[str]:
    """Return one password per Pi-hole; an empty string means "no authentication".

    ``PIHOLE_PASSWORD_FILE`` takes precedence over ``PIHOLE_PASSWORD``. The legacy names
    ``PIHOLE_APP_PASSWORD_FILE`` / ``PIHOLE_APP_PASSWORD`` are used as fallback. A single
    value applies to every Pi-hole; a comma-separated list assigns one value per Pi-hole.
    """
    for file_var in ("PIHOLE_PASSWORD_FILE", "PIHOLE_APP_PASSWORD_FILE"):
        raw = env.get(file_var, "").strip()
        if raw:
            paths = [p.strip() for p in raw.split(",")]
            if len(paths) == 1:
                return [_read_file(paths[0])] * count
            if len(paths) != count:
                raise ConfigError(
                    f"{file_var} lists {len(paths)} files but PIHOLE_URL lists {count} Pi-holes"
                )
            return [_read_file(p) if p else "" for p in paths]

    for var in ("PIHOLE_PASSWORD", "PIHOLE_APP_PASSWORD"):
        raw = env.get(var, "")
        if raw.strip():
            if count > 1 and "," in raw:
                parts = [p.strip() for p in raw.split(",")]
                if len(parts) == count:
                    return parts
            # A single password for all instances (it may contain commas itself).
            return [raw.strip()] * count
    return [""] * count


def _ip(name: str, value: str | None, version: int) -> str | None:
    if not value or not value.strip():
        return None
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        raise ConfigError(f"{name} is not a valid IP address: {value!r}") from None
    if ip.version != version:
        raise ConfigError(f"{name} must be an IPv{version} address, got {value!r}")
    return str(ip)


def load(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env

    urls = [u.rstrip("/") for u in parse_list(env.get("PIHOLE_URL"))]
    if not urls:
        raise ConfigError("PIHOLE_URL is required (comma-separated for several Pi-holes)")
    if len(set(urls)) != len(urls):
        raise ConfigError("PIHOLE_URL contains duplicates")
    passwords = resolve_passwords(env, len(urls))
    piholes = tuple(PiholeConfig(u, p) for u, p in zip(urls, passwords, strict=True))

    record_type = env.get("RECORD_TYPE", A).strip().upper() or A
    if record_type not in (A, CNAME):
        raise ConfigError(f"RECORD_TYPE must be A or CNAME, got {record_type!r}")

    target_ip = _ip("TARGET_IP", env.get("TARGET_IP"), 4)
    target_ipv6 = _ip("TARGET_IPV6", env.get("TARGET_IPV6"), 6)
    cname_target = env.get("CNAME_TARGET", "").strip().lower().rstrip(".") or None

    if record_type == A and not (target_ip or target_ipv6):
        raise ConfigError("RECORD_TYPE=A needs TARGET_IP and/or TARGET_IPV6")
    if record_type == CNAME and not cname_target:
        raise ConfigError("RECORD_TYPE=CNAME needs CNAME_TARGET")

    domains_raw = env.get("DOMAINS") or env.get("ALLOWED_ZONE") or ""
    domains = tuple(sorted({d.lower().strip(".") for d in parse_list(domains_raw) if d.strip(".")}))

    interval = parse_int("SYNC_INTERVAL", env.get("SYNC_INTERVAL"), 60, minimum=1)
    default_health_age = max(300, 3 * interval)

    return Config(
        traefik_url=env.get("TRAEFIK_API_URL", "http://traefik:8080").strip().rstrip("/"),
        piholes=piholes,
        record_type=record_type,
        target_ip=target_ip,
        target_ipv6=target_ipv6,
        cname_target=cname_target,
        domains=domains,
        include_apex=parse_bool("INCLUDE_APEX", env.get("INCLUDE_APEX"), False),
        tcp_routers=parse_bool("TRAEFIK_TCP_ROUTERS", env.get("TRAEFIK_TCP_ROUTERS"), False),
        verify_tls=parse_verify_tls(env.get("PIHOLE_VERIFY_TLS")),
        interval=interval,
        delete_threshold=parse_int("DELETE_THRESHOLD", env.get("DELETE_THRESHOLD"), 3, minimum=1),
        dry_run=parse_bool("DRY_RUN", env.get("DRY_RUN"), False),
        state_file=env.get("STATE_FILE", "").strip() or DEFAULT_STATE_FILE,
        health_file=env.get("HEALTH_FILE", "").strip() or DEFAULT_HEALTH_FILE,
        health_max_age=parse_int(
            "HEALTH_MAX_AGE", env.get("HEALTH_MAX_AGE"), default_health_age, minimum=1
        ),
        heartbeat=parse_int("HEARTBEAT", env.get("HEARTBEAT"), 3600),
        write_delay=parse_float("WRITE_DELAY", env.get("WRITE_DELAY"), 0.5),
        max_retries=parse_int("MAX_RETRIES", env.get("MAX_RETRIES"), 5, minimum=1),
        request_timeout=parse_int("REQUEST_TIMEOUT", env.get("REQUEST_TIMEOUT"), 10, minimum=1),
        log_level=(env.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"),
    )
