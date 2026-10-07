import json

import pytest

from traefik_pihole_sync import state
from traefik_pihole_sync.records import CNAME, A, Record

URLS = ["http://a", "http://b"]


def test_missing_file_gives_empty_state(tmp_path):
    st, migrated = state.load(str(tmp_path / "state.json"), URLS, "10.0.0.1")
    assert st == {"http://a": set(), "http://b": set()}
    assert not migrated


def test_roundtrip(tmp_path):
    path = str(tmp_path / "sub" / "state.json")
    st = {
        "http://a": {Record(A, "x.example.com", "10.0.0.1")},
        "http://b": {Record(CNAME, "y.example.com", "x.example.com")},
    }
    state.save(path, st)
    data = json.loads((tmp_path / "sub" / "state.json").read_text())
    assert data["version"] == 2
    loaded, migrated = state.load(path, URLS, None)
    assert loaded == st and not migrated


def test_migrate_v1_in_place(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(["a.example.com", "b.example.com"]))
    st, migrated = state.load(str(path), URLS, "10.0.0.1")
    assert migrated
    assert st["http://a"] == {
        Record(A, "a.example.com", "10.0.0.1"),
        Record(A, "b.example.com", "10.0.0.1"),
    }
    assert st["http://b"] == set()


def test_migrate_legacy_file_name(tmp_path):
    (tmp_path / "managed_hosts.json").write_text(json.dumps(["a.example.com"]))
    st, migrated = state.load(str(tmp_path / "state.json"), ["http://a"], "10.0.0.1")
    assert migrated
    assert st == {"http://a": {Record(A, "a.example.com", "10.0.0.1")}}
    # The legacy file stays untouched.
    assert json.loads((tmp_path / "managed_hosts.json").read_text()) == ["a.example.com"]


def test_state_file_wins_over_legacy_file(tmp_path):
    (tmp_path / "managed_hosts.json").write_text(json.dumps(["old.example.com"]))
    state.save(str(tmp_path / "state.json"), {"http://a": set()})
    st, migrated = state.load(str(tmp_path / "state.json"), ["http://a"], "10.0.0.1")
    assert st == {"http://a": set()} and not migrated


def test_migration_needs_target_ip(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(["a.example.com"]))
    with pytest.raises(state.StateError):
        state.load(str(path), URLS, None)


def test_migrate_empty_list_without_target_ip(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[]")
    st, _ = state.load(str(path), URLS, None)
    assert st == {"http://a": set(), "http://b": set()}


def test_broken_file_raises(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    with pytest.raises(state.StateError):
        state.load(str(path), URLS, "10.0.0.1")


def test_unknown_version_raises(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 99}))
    with pytest.raises(state.StateError):
        state.load(str(path), URLS, "10.0.0.1")


def test_unconfigured_pihole_is_kept(tmp_path):
    path = str(tmp_path / "state.json")
    state.save(path, {"http://old": {Record(A, "x.example.com", "10.0.0.1")}})
    st, _ = state.load(path, ["http://a"], None)
    assert st["http://old"] == {Record(A, "x.example.com", "10.0.0.1")}
    assert st["http://a"] == set()


@pytest.mark.parametrize(
    "piholes",
    [
        {"http://a": [{"type": "TXT", "name": "x", "value": "y"}]},
        {"http://a": [{"name": "x"}]},
        {"http://a": ["x.example.com"]},
        ["not", "a", "dict"],
    ],
)
def test_invalid_records_raise_state_error(tmp_path, piholes):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 2, "piholes": piholes}))
    with pytest.raises(state.StateError):
        state.load(str(path), URLS, "10.0.0.1")
