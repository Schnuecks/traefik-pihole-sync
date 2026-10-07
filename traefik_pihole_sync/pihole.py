"""Minimal client for the Pi-hole v6 local DNS API."""

from __future__ import annotations

import logging
import time
from urllib.parse import quote

import requests
import urllib3

from .records import AAAA, CNAME, A, Record

log = logging.getLogger(__name__)

# Upper bound for a Retry-After header, so a misbehaving server cannot stall the loop.
MAX_RETRY_AFTER = 300.0


class PiholeError(RuntimeError):
    pass


def parse_host_entry(entry: str) -> list[Record]:
    """``"<ip> <name> [<name> ...]"`` -> A/AAAA records."""
    parts = entry.split()
    if len(parts) < 2:
        return []
    ip, names = parts[0], parts[1:]
    rtype = AAAA if ":" in ip else A
    return [Record(rtype, name, ip) for name in names]


def parse_cname_entry(entry: str) -> list[Record]:
    """``"<name>,<target>[,<ttl>]"`` -> CNAME record. Pi-hole allows several names."""
    parts = [p.strip() for p in entry.split(",")]
    if len(parts) < 2:
        return []
    if len(parts) > 2 and parts[-1].isdigit():
        parts = parts[:-1]
    *names, target = parts
    return [Record(CNAME, name, target) for name in names if name]


def _path(record: Record) -> str:
    if record.type == CNAME:
        return f"cnameRecords/{quote(f'{record.name},{record.value}', safe='')}"
    return f"hosts/{quote(f'{record.value} {record.name}', safe='')}"


class PiholeClient:
    def __init__(
        self,
        base_url: str,
        password: str = "",  # nosec B107 - empty means "no authentication"
        verify_tls: bool | str = True,
        timeout: int = 10,
        max_retries: int = 5,
        retry_delay: float = 5.0,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._password = password
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.sid: str | None = None
        self.session = session or requests.Session()
        self.session.verify = verify_tls
        if verify_tls is False:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def __repr__(self) -> str:
        return f"PiholeClient({self.base_url!r})"

    # --- session handling -------------------------------------------------

    def _send(self, method: str, url: str, **kwargs) -> requests.Response:
        """Send a request, retrying connection errors and HTTP 429."""
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                # Never follow redirects: they would carry the session ID (and, for the
                # login, the password) to whatever address the server names.
                resp = self.session.request(
                    method, url, timeout=self.timeout, allow_redirects=False, **kwargs
                )
            except requests.RequestException as e:
                last_error = e
                log.debug(
                    "%s %s failed (attempt %d/%d): %s", method, url, attempt, self.max_retries, e
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                continue
            if resp.status_code == 429:
                try:
                    wait = float(resp.headers.get("Retry-After", 30))
                except ValueError:
                    wait = 30.0
                wait = min(max(wait, 0.0), MAX_RETRY_AFTER)
                log.warning("Pi-hole rate limit (429) on %s %s, waiting %.0fs", method, url, wait)
                last_error = PiholeError("rate limited")
                if attempt < self.max_retries:
                    time.sleep(wait)
                continue
            if resp.is_redirect:
                raise PiholeError(
                    f"{url} redirects to {resp.headers.get('Location', '?')}; "
                    "set PIHOLE_URL to the final address"
                )
            return resp
        raise PiholeError(
            f"{method} {url}: giving up after {self.max_retries} attempts: {last_error}"
        )

    def authenticate(self) -> None:
        if not self._password:
            log.debug("No password configured for %s, skipping authentication", self.base_url)
            return
        resp = self._send("POST", f"{self.base_url}/api/auth", json={"password": self._password})
        if resp.status_code == 401:
            raise PiholeError(f"{self.base_url}: authentication failed (wrong password?)")
        resp.raise_for_status()
        session = resp.json().get("session", {})
        self.sid = session.get("sid")
        if self.sid:
            log.info("Authenticated at %s", self.base_url)

    def logout(self) -> None:
        if not self.sid:
            return
        try:
            self.session.delete(
                f"{self.base_url}/api/auth",
                headers=self._headers(),
                timeout=5,
                allow_redirects=False,
            )
            log.info("Logged out from %s", self.base_url)
        except requests.RequestException as e:
            log.warning("Logout from %s failed: %s", self.base_url, e)
        self.sid = None

    def _headers(self) -> dict[str, str]:
        # The SID header needs no CSRF token (that is only required for cookie auth).
        return {"X-FTL-SID": self.sid} if self.sid else {}

    def _request(self, method: str, path: str) -> requests.Response:
        url = f"{self.base_url}/api/{path}"
        if self._password and not self.sid:
            self.authenticate()
        resp = self._send(method, url, headers=self._headers())
        if resp.status_code == 401:
            if not self._password:
                raise PiholeError(f"{self.base_url}: authentication required, set PIHOLE_PASSWORD")
            log.info("Pi-hole session at %s expired, re-authenticating", self.base_url)
            self.sid = None
            self.authenticate()
            resp = self._send(method, url, headers=self._headers())
        return resp

    # --- DNS records ------------------------------------------------------

    def _get_list(self, key: str) -> list[str]:
        resp = self._request("GET", f"config/dns/{key}")
        resp.raise_for_status()
        return resp.json().get("config", {}).get("dns", {}).get(key, []) or []

    def get_records(self) -> set[Record]:
        records: set[Record] = set()
        for entry in self._get_list("hosts"):
            records.update(parse_host_entry(entry))
        for entry in self._get_list("cnameRecords"):
            records.update(parse_cname_entry(entry))
        return records

    @staticmethod
    def _error_text(resp: requests.Response) -> str:
        try:
            err = resp.json().get("error", {})
            return f"{err.get('message', '')} {err.get('hint') or ''}".strip()
        except ValueError:
            return resp.text[:200]

    def add_record(self, record: Record) -> None:
        resp = self._request("PUT", f"config/dns/{_path(record)}")
        if resp.status_code == 400 and "already present" in self._error_text(resp).lower():
            log.debug("%s already present in %s", record, self.base_url)
            return
        if not resp.ok:
            raise PiholeError(
                f"adding {record} failed: HTTP {resp.status_code} {self._error_text(resp)}"
            )

    def delete_record(self, record: Record) -> None:
        resp = self._request("DELETE", f"config/dns/{_path(record)}")
        if resp.status_code == 404:
            log.debug("%s was already gone from %s", record, self.base_url)
            return
        if not resp.ok:
            raise PiholeError(
                f"deleting {record} failed: HTTP {resp.status_code} {self._error_text(resp)}"
            )
