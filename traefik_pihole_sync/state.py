"""State file: the records this tool created, per Pi-hole.

Format v2::

    {"version": 2, "piholes": {"<url>": [{"type": "A", "name": "...", "value": "..."}]}}

Version 1 (the original script) was a plain list of hostnames, all pointing to TARGET_IP
in a single Pi-hole. It is migrated to A records of the first configured Pi-hole.
"""

from __future__ import annotations

import json
import logging
import os

from .records import A, Record

log = logging.getLogger(__name__)

VERSION = 2
LEGACY_FILE_NAME = "managed_hosts.json"

State = dict[str, set[Record]]


class StateError(RuntimeError):
    pass


def migrate_v1(hostnames: list, pihole_urls: list[str], target_ip: str | None) -> State:
    if not pihole_urls:
        raise StateError("no Pi-hole configured")
    if hostnames and not target_ip:
        raise StateError(
            "the old state file lists hostnames as A records, set TARGET_IP to migrate it"
        )
    records = {Record(A, str(h), target_ip) for h in hostnames if str(h).strip()}
    state: State = {url: set() for url in pihole_urls}
    state[pihole_urls[0]] = records
    return state


def from_json(data, pihole_urls: list[str], target_ip: str | None) -> State:
    if isinstance(data, list):
        return migrate_v1(data, pihole_urls, target_ip)
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise StateError(f"unsupported state format (expected version {VERSION})")
    state: State = {}
    try:
        for url, records in (data.get("piholes") or {}).items():
            state[url.rstrip("/")] = {Record.from_dict(r) for r in records}
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise StateError(f"invalid record in state file: {e!r}") from None
    for url in pihole_urls:
        state.setdefault(url, set())
    return state


def to_json(state: State) -> dict:
    return {
        "version": VERSION,
        "piholes": {
            url: [r.to_dict() for r in sorted(records)] for url, records in sorted(state.items())
        },
    }


def load(path: str, pihole_urls: list[str], target_ip: str | None) -> tuple[State, bool]:
    """Load the state; returns ``(state, migrated)``.

    If ``path`` does not exist, a legacy ``managed_hosts.json`` in the same directory is
    migrated. A broken file raises instead of starting empty: an empty state would only
    lose track of records, but a silent reset hides the problem.
    """
    source = path
    if not os.path.isfile(path):
        legacy = os.path.join(os.path.dirname(path) or ".", LEGACY_FILE_NAME)
        if os.path.abspath(legacy) != os.path.abspath(path) and os.path.isfile(legacy):
            source = legacy
        else:
            log.info("No state file found at %s, starting with an empty state", path)
            return {url: set() for url in pihole_urls}, False

    try:
        with open(source, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise StateError(f"cannot read state file {source}: {e}") from None

    state = from_json(data, pihole_urls, target_ip)
    migrated = source != path or isinstance(data, list)
    if migrated:
        count = sum(len(r) for r in state.values())
        log.info("Migrated old state file %s (%d record(s)) to format v%d", source, count, VERSION)
    else:
        log.info("Loaded state: %d record(s)", sum(len(r) for r in state.values()))
    for url in state:
        if url not in pihole_urls and state[url]:
            log.warning(
                "State lists %d record(s) for %s, which is no longer configured; "
                "they are kept but not managed",
                len(state[url]),
                url,
            )
    return state, migrated


def save(path: str, state: State) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(to_json(state), f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
