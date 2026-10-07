"""Sync loop, logging and command line."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field

from . import __version__, state
from .config import DEFAULT_HEALTH_FILE, Config, ConfigError, load
from .pihole import PiholeClient
from .plan import build_plan, desired_records
from .records import Record
from .traefik import TraefikClient, filter_hosts

log = logging.getLogger("traefik_pihole_sync")


class FailureLog:
    """Report a failing source once and its recovery once, instead of every cycle."""

    def __init__(self) -> None:
        self.failing: dict[str, float] = {}

    def failed(self, source: str, message: str) -> None:
        if source not in self.failing:
            self.failing[source] = time.time()
            log.warning("%s (further failures are only logged at DEBUG)", message)
        else:
            log.debug(message)

    def ok(self, source: str) -> None:
        since = self.failing.pop(source, None)
        if since is not None:
            log.info("%s is reachable again (after %.0fs)", source, time.time() - since)


@dataclass
class Instance:
    client: PiholeClient
    managed: set[Record]
    missing: dict[Record, int] = field(default_factory=dict)
    warned_conflicts: set[str] = field(default_factory=set)
    existing_count: int = 0

    @property
    def url(self) -> str:
        return self.client.base_url


class Syncer:
    def __init__(
        self, cfg: Config, traefik: TraefikClient, instances: list[Instance], st: state.State
    ):
        self.cfg = cfg
        self.traefik = traefik
        self.instances = instances
        self.state = st
        self.failures = FailureLog()
        self.desired_count = 0

    @classmethod
    def from_config(cls, cfg: Config) -> Syncer:
        urls = [p.url for p in cfg.piholes]
        st, migrated = state.load(cfg.state_file, urls, cfg.target_ip)
        instances = [
            Instance(
                client=PiholeClient(
                    p.url,
                    p.password,
                    verify_tls=cfg.verify_tls,
                    timeout=cfg.request_timeout,
                    max_retries=cfg.max_retries,
                ),
                managed=set(st[p.url]),
            )
            for p in cfg.piholes
        ]
        syncer = cls(cfg, TraefikClient(cfg.traefik_url, cfg.request_timeout), instances, st)
        if migrated and not cfg.dry_run:
            syncer.save_state()
        return syncer

    def save_state(self) -> None:
        for inst in self.instances:
            self.state[inst.url] = set(inst.managed)
        state.save(self.cfg.state_file, self.state)

    def desired(self, hostnames: set[str]) -> set[Record]:
        hosts = filter_hosts(hostnames, self.cfg.domains, self.cfg.include_apex)
        return desired_records(
            hosts,
            self.cfg.record_type,
            target_ip=self.cfg.target_ip,
            target_ipv6=self.cfg.target_ipv6,
            cname_target=self.cfg.cname_target,
        )

    def run_once(self) -> tuple[bool, int]:
        """One sync cycle over all Pi-holes. Returns ``(success, changes)``."""
        try:
            hostnames = self.traefik.get_hostnames(tcp=self.cfg.tcp_routers)
            self.failures.ok("Traefik API")
        except Exception as e:
            self.failures.failed("Traefik API", f"Cannot read routers from Traefik API: {e}")
            return False, 0

        desired = self.desired(hostnames)
        self.desired_count = len(desired)
        log.debug("Traefik: %d hostname(s), %d desired record(s)", len(hostnames), len(desired))
        if not desired:
            log.debug("No matching hostnames found in Traefik")

        success, changes = True, 0
        for inst in self.instances:
            try:
                changes += self.sync_instance(inst, desired)
                self.failures.ok(inst.url)
            except Exception as e:
                success = False
                self.failures.failed(inst.url, f"Sync with Pi-hole {inst.url} failed: {e}")
        return success, changes

    def sync_instance(self, inst: Instance, desired: set[Record]) -> int:
        existing = inst.client.get_records()
        inst.existing_count = len(existing)
        plan = build_plan(desired, existing, inst.managed, inst.missing, self.cfg.delete_threshold)
        dry = self.cfg.dry_run
        tag = " (dry run)" if dry else ""
        changes = 0

        new_conflicts = plan.conflicts - inst.warned_conflicts
        for name in sorted(new_conflicts):
            log.warning(
                "%s: %s already has records not created by this tool, leaving it alone",
                inst.url,
                name,
            )
        inst.warned_conflicts = set(plan.conflicts)

        for record, count in plan.deferred.items():
            if inst.missing.get(record) != count:
                log.info(
                    "%s: %s missing from Traefik (%d/%d), deletion postponed",
                    inst.url,
                    record,
                    count,
                    self.cfg.delete_threshold,
                )
        inst.missing = dict(plan.deferred)

        for record in plan.forget:
            log.info("%s: %s is already gone from Pi-hole, forgetting it%s", inst.url, record, tag)
            if not dry:
                inst.managed.discard(record)
                changes += 1

        for record in plan.delete:
            log.info("%s: delete %s%s", inst.url, record, tag)
            if dry:
                continue
            try:
                inst.client.delete_record(record)
            except Exception as e:
                log.error("%s: deleting %s failed: %s", inst.url, record, e)
                continue
            inst.managed.discard(record)
            changes += 1
            time.sleep(self.cfg.write_delay)

        for record in plan.add:
            log.info("%s: add %s%s", inst.url, record, tag)
            if dry:
                continue
            try:
                inst.client.add_record(record)
            except Exception as e:
                log.error("%s: adding %s failed: %s", inst.url, record, e)
                continue
            inst.managed.add(record)
            changes += 1
            time.sleep(self.cfg.write_delay)

        if changes:
            self.save_state()
        return changes

    def logout(self) -> None:
        for inst in self.instances:
            inst.client.logout()


def touch(path: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{time.time():.0f}\n")
    except OSError as e:
        log.warning("Cannot write health file %s: %s", path, e)


def healthcheck(env=os.environ) -> int:
    """Exit code 0 if the last successful sync is recent enough."""
    path = env.get("HEALTH_FILE", "").strip() or DEFAULT_HEALTH_FILE
    try:
        interval = int(env.get("SYNC_INTERVAL", "60"))
        max_age = int(env.get("HEALTH_MAX_AGE", "") or max(300, 3 * interval))
    except ValueError:
        max_age = 300
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        print(f"unhealthy: no successful sync yet ({path} missing)")
        return 1
    if age > max_age:
        print(f"unhealthy: last successful sync {age:.0f}s ago (limit {max_age}s)")
        return 1
    print(f"healthy: last successful sync {age:.0f}s ago")
    return 0


def run_loop(syncer: Syncer, cfg: Config) -> None:
    last_heartbeat = time.time()
    cycles = changes_total = 0
    while True:
        started = time.time()
        try:
            ok, changes = syncer.run_once()
        except Exception:
            log.exception("Unexpected error in sync cycle")
            ok, changes = False, 0
        if ok:
            touch(cfg.health_file)
            cycles += 1
            changes_total += changes

        if cfg.heartbeat > 0 and time.time() - last_heartbeat >= cfg.heartbeat:
            managed = sum(len(i.managed) for i in syncer.instances)
            msg = (
                f"Status: {cycles} successful cycle(s), {changes_total} change(s) | "
                f"desired {syncer.desired_count}, managed {managed}"
            )
            if syncer.failures.failing:
                msg += f" | failing: {', '.join(syncer.failures.failing)}"
            log.info(msg)
            last_heartbeat = time.time()
            cycles = changes_total = 0

        log.debug("Cycle took %.2fs, next in %ds", time.time() - started, cfg.interval)
        time.sleep(cfg.interval)


def describe(cfg: Config) -> str:
    parts = [
        f"v{__version__}",
        f"mode {cfg.record_type}",
        f"Pi-holes {', '.join(p.url for p in cfg.piholes)}",
    ]
    if cfg.target_ip:
        parts.append(f"IPv4 {cfg.target_ip}")
    if cfg.target_ipv6:
        parts.append(f"IPv6 {cfg.target_ipv6}")
    if cfg.cname_target:
        parts.append(f"CNAME target {cfg.cname_target}")
    parts.append(f"domains {', '.join(cfg.domains) if cfg.domains else 'all'}")
    parts.append(f"interval {cfg.interval}s")
    if cfg.include_apex:
        parts.append("apex")
    if cfg.tcp_routers:
        parts.append("TCP routers")
    if cfg.verify_tls is False:
        parts.append("TLS verification OFF")
    if cfg.dry_run:
        parts.append("DRY RUN")
    return "traefik-pihole-sync " + " | ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="traefik-pihole-sync",
        description="Sync Traefik router hostnames into Pi-hole v6 local DNS records.",
    )
    parser.add_argument("--healthcheck", action="store_true", help="check the health file and exit")
    parser.add_argument("--once", action="store_true", help="run a single sync cycle and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.healthcheck:
        return healthcheck()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    # requests/urllib3 log every connection at DEBUG; keep them quiet.
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    try:
        cfg = load()
        if cfg.include_apex and not cfg.domains:
            log.warning("INCLUDE_APEX has no effect without DOMAINS")
        syncer = Syncer.from_config(cfg)
    except (ConfigError, state.StateError) as e:
        log.error("%s", e)
        return 2

    log.info(describe(cfg))
    # docker stop sends SIGTERM: exit through the finally block to log out of Pi-hole.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        if args.once:
            ok, _ = syncer.run_once()
            if ok:
                touch(cfg.health_file)
            return 0 if ok else 1
        run_loop(syncer, cfg)
    except KeyboardInterrupt:
        pass
    finally:
        syncer.logout()
        log.info("traefik-pihole-sync stopped")
    return 0
