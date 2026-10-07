"""Read routers from the Traefik API and extract hostnames from their rules."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

import requests

log = logging.getLogger(__name__)

PER_PAGE = 100
MAX_PAGES = 1000

# Matcher name followed by its argument list, e.g. Host(`a.example.com`, `b.example.com`).
# HostRegexp/HostSNIRegexp do not match because the name must be followed by "(".
_MATCHER = {
    "Host": re.compile(r"\bHost\s*\(([^)]*)\)"),
    "HostSNI": re.compile(r"\bHostSNI\s*\(([^)]*)\)"),
}
_VALUE = re.compile(r"`([^`]*)`|\"([^\"]*)\"")
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def is_valid_hostname(name: str) -> bool:
    if not name or len(name) > 253:
        return False
    return all(_LABEL.match(label) for label in name.split("."))


def extract_hosts(rule: str, matcher: str = "Host") -> set[str]:
    """Return the literal hostnames of all ``Host``/``HostSNI`` matchers in a rule.

    Negated matchers (``!Host(...)``), wildcards and placeholders are skipped.
    """
    hosts: set[str] = set()
    for match in _MATCHER[matcher].finditer(rule or ""):
        if rule[: match.start()].rstrip().endswith("!"):
            continue
        for backtick, quoted in _VALUE.findall(match.group(1)):
            name = (backtick or quoted).strip().lower().rstrip(".")
            if "*" in name or "{" in name or "}" in name:
                continue
            if is_valid_hostname(name):
                hosts.add(name)
            elif name:
                log.debug("Skipping invalid hostname %r", name)
    return hosts


def domain_of(hostname: str, domains: Iterable[str]) -> str | None:
    """Return the longest configured domain that contains ``hostname``."""
    best = None
    for domain in domains:
        inside = hostname == domain or hostname.endswith("." + domain)
        if inside and (best is None or len(domain) > len(best)):
            best = domain
    return best


def filter_hosts(
    hostnames: Iterable[str], domains: tuple[str, ...], include_apex: bool
) -> set[str]:
    """Keep hostnames inside ``domains`` (all if empty) and optionally add each apex."""
    if not domains:
        return set(hostnames)
    result: set[str] = set()
    for name in hostnames:
        domain = domain_of(name, domains)
        if domain is None:
            continue
        result.add(name)
        if include_apex:
            result.add(domain)
    return result


class TraefikClient:
    def __init__(self, base_url: str, timeout: int = 10, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get_routers(self, protocol: str) -> list[dict]:
        """Fetch all routers of one protocol, following the X-Next-Page header."""
        routers: list[dict] = []
        page = 1
        for _ in range(MAX_PAGES):
            resp = self.session.get(
                f"{self.base_url}/api/{protocol}/routers",
                params={"page": page, "per_page": PER_PAGE},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise ValueError(f"unexpected response from Traefik /api/{protocol}/routers")
            routers.extend(data)
            try:
                next_page = int(resp.headers.get("X-Next-Page", "0"))
            except ValueError:
                next_page = 0
            # Traefik answers X-Next-Page: 1 on the last page.
            if next_page <= page:
                return routers
            page = next_page
        raise RuntimeError(f"Traefik /api/{protocol}/routers: more than {MAX_PAGES} pages")

    def get_hostnames(self, tcp: bool = False) -> set[str]:
        hostnames: set[str] = set()
        sources = [("http", "Host")] + ([("tcp", "HostSNI")] if tcp else [])
        for protocol, matcher in sources:
            routers = self._get_routers(protocol)
            log.debug("Traefik returned %d %s router(s)", len(routers), protocol.upper())
            for router in routers:
                found = extract_hosts(router.get("rule", ""), matcher)
                if found:
                    log.debug("Router %s: %s", router.get("name", "?"), ", ".join(sorted(found)))
                hostnames |= found
        return hostnames
