"""End-to-end sync cycles against in-memory fakes of Traefik and Pi-hole."""

import json
import logging
import os
import time

import pytest

from traefik_pihole_sync import main
from traefik_pihole_sync.config import load
from traefik_pihole_sync.main import Instance, Syncer
from traefik_pihole_sync.records import AAAA, CNAME, A, Record

IP = "10.0.0.1"


class FakeTraefik:
    def __init__(self, hosts):
        self.hosts = set(hosts)
        self.fail = False

    def get_hostnames(self, tcp=False):
        if self.fail:
            raise RuntimeError("connection refused")
        return set(self.hosts)


class FakePihole:
    def __init__(self, url, records=()):
        self.base_url = url
        self.records = set(records)
        self.fail = False
        self.logged_out = False

    def get_records(self):
        if self.fail:
            raise RuntimeError("down")
        return set(self.records)

    def add_record(self, record):
        self.records.add(record)

    def delete_record(self, record):
        self.records.discard(record)

    def logout(self):
        self.logged_out = True


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda s: None)


def make(tmp_path, hosts, piholes=None, **env):
    environment = {
        "PIHOLE_URL": "http://p1",
        "TARGET_IP": IP,
        "STATE_FILE": str(tmp_path / "state.json"),
        "WRITE_DELAY": "0",
        **env,
    }
    cfg = load(environment)
    piholes = piholes or [FakePihole(p.url) for p in cfg.piholes]
    traefik = FakeTraefik(hosts)
    st = {p.base_url: set() for p in piholes}
    syncer = Syncer(cfg, traefik, [Instance(p, set()) for p in piholes], st)
    return syncer, traefik, piholes


def saved(tmp_path):
    return json.loads((tmp_path / "state.json").read_text())


def test_adds_records_and_saves_state(tmp_path):
    syncer, _, [ph] = make(tmp_path, {"a.example.com"})
    ok, changes = syncer.run_once()
    assert ok and changes == 1
    assert ph.records == {Record(A, "a.example.com", IP)}
    assert saved(tmp_path)["piholes"]["http://p1"] == [
        {"type": "A", "name": "a.example.com", "value": IP}
    ]


def test_dry_run_changes_nothing(tmp_path):
    syncer, _, [ph] = make(tmp_path, {"a.example.com"}, DRY_RUN="true")
    ok, changes = syncer.run_once()
    assert ok and changes == 0
    assert ph.records == set()
    assert not (tmp_path / "state.json").exists()


def test_delete_after_threshold(tmp_path):
    syncer, traefik, [ph] = make(tmp_path, {"a.example.com"}, DELETE_THRESHOLD="2")
    syncer.run_once()
    traefik.hosts = set()
    syncer.run_once()
    assert ph.records == {Record(A, "a.example.com", IP)}
    syncer.run_once()
    assert ph.records == set()
    assert saved(tmp_path)["piholes"]["http://p1"] == []


def test_foreign_records_untouched(tmp_path):
    foreign = Record(A, "a.example.com", "10.9.9.9")
    other = Record(A, "manual.example.com", "10.9.9.9")
    ph = FakePihole("http://p1", {foreign, other})
    syncer, traefik, _ = make(tmp_path, {"a.example.com"}, piholes=[ph], DELETE_THRESHOLD="1")
    syncer.run_once()
    traefik.hosts = set()
    syncer.run_once()
    assert ph.records == {foreign, other}


def test_conflict_warning_only_once(tmp_path, caplog):
    ph = FakePihole("http://p1", {Record(A, "a.example.com", "10.9.9.9")})
    syncer, _, _ = make(tmp_path, {"a.example.com"}, piholes=[ph])
    for _ in range(3):
        syncer.run_once()
    assert sum("not created by this tool" in r.message for r in caplog.records) == 1


def test_traefik_failure_is_reported_once(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    syncer, traefik, [ph] = make(tmp_path, {"a.example.com"})
    traefik.fail = True
    for _ in range(3):
        ok, _ = syncer.run_once()
        assert not ok
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    traefik.fail = False
    assert syncer.run_once()[0]
    assert any("reachable again" in r.message for r in caplog.records)


def test_multiple_piholes_have_separate_state(tmp_path):
    p1, p2 = (
        FakePihole("http://p1"),
        FakePihole("http://p2", {Record(A, "a.example.com", "1.2.3.4")}),
    )
    syncer, _, _ = make(
        tmp_path, {"a.example.com"}, piholes=[p1, p2], PIHOLE_URL="http://p1,http://p2"
    )
    syncer.run_once()
    assert p1.records == {Record(A, "a.example.com", IP)}
    assert p2.records == {Record(A, "a.example.com", "1.2.3.4")}
    data = saved(tmp_path)["piholes"]
    assert len(data["http://p1"]) == 1 and data["http://p2"] == []


def test_one_failing_pihole_does_not_block_others(tmp_path):
    p1, p2 = FakePihole("http://p1"), FakePihole("http://p2")
    p1.fail = True
    syncer, _, _ = make(
        tmp_path, {"a.example.com"}, piholes=[p1, p2], PIHOLE_URL="http://p1,http://p2"
    )
    ok, _ = syncer.run_once()
    assert not ok
    assert p2.records == {Record(A, "a.example.com", IP)}


def test_cname_mode(tmp_path):
    syncer, _, [ph] = make(
        tmp_path,
        {"a.example.com", "b.example.com"},
        RECORD_TYPE="CNAME",
        CNAME_TARGET="proxy.example.com",
    )
    syncer.run_once()
    assert ph.records == {
        Record(CNAME, "a.example.com", "proxy.example.com"),
        Record(CNAME, "b.example.com", "proxy.example.com"),
        Record(A, "proxy.example.com", IP),
    }


def test_ipv6_records(tmp_path):
    syncer, _, [ph] = make(tmp_path, {"a.example.com"}, TARGET_IPV6="fd00::1")
    syncer.run_once()
    assert ph.records == {Record(A, "a.example.com", IP), Record(AAAA, "a.example.com", "fd00::1")}


def test_domains_and_apex(tmp_path):
    syncer, _, [ph] = make(
        tmp_path,
        {"a.home.example.co.uk", "x.other.org"},
        DOMAINS="home.example.co.uk",
        INCLUDE_APEX="true",
    )
    syncer.run_once()
    assert {r.name for r in ph.records} == {"a.home.example.co.uk", "home.example.co.uk"}


def test_migration_then_sync(tmp_path):
    (tmp_path / "managed_hosts.json").write_text(json.dumps(["a.example.com", "old.example.com"]))
    ph = FakePihole("http://p1", {Record(A, "a.example.com", IP), Record(A, "old.example.com", IP)})
    cfg = load(
        {
            "PIHOLE_URL": "http://p1",
            "TARGET_IP": IP,
            "STATE_FILE": str(tmp_path / "state.json"),
            "DELETE_THRESHOLD": "1",
            "WRITE_DELAY": "0",
        }
    )
    syncer = Syncer.from_config(cfg)
    assert (tmp_path / "state.json").exists()
    syncer.traefik = FakeTraefik({"a.example.com"})
    syncer.instances[0].client = ph
    syncer.run_once()
    # The migrated record is recognised as ours and can be deleted.
    assert ph.records == {Record(A, "a.example.com", IP)}


def test_logout_all(tmp_path):
    p1, p2 = FakePihole("http://p1"), FakePihole("http://p2")
    syncer, _, _ = make(tmp_path, set(), piholes=[p1, p2], PIHOLE_URL="http://p1,http://p2")
    syncer.logout()
    assert p1.logged_out and p2.logged_out


def test_healthcheck(tmp_path):
    health = tmp_path / "health"
    env = {"HEALTH_FILE": str(health), "HEALTH_MAX_AGE": "60"}
    assert main.healthcheck(env) == 1
    main.touch(str(health))
    assert main.healthcheck(env) == 0
    old = time.time() - 120
    os.utime(health, (old, old))
    assert main.healthcheck(env) == 1
