import pytest

from traefik_pihole_sync.plan import build_plan, desired_records
from traefik_pihole_sync.records import AAAA, CNAME, A, Record

IP = "10.0.0.1"
IP6 = "fd00::1"


def a(name, ip=IP):
    return Record(A, name, ip)


def test_desired_a_records():
    assert desired_records({"x.example.com"}, A, target_ip=IP) == {a("x.example.com")}


def test_desired_a_and_aaaa():
    result = desired_records({"x.example.com"}, A, target_ip=IP, target_ipv6=IP6)
    assert result == {a("x.example.com"), Record(AAAA, "x.example.com", IP6)}


def test_desired_cname_with_target_address():
    result = desired_records(
        {"x.example.com", "proxy.example.com"},
        CNAME,
        target_ip=IP,
        cname_target="proxy.example.com",
    )
    assert result == {
        Record(CNAME, "x.example.com", "proxy.example.com"),
        a("proxy.example.com"),
    }


def test_desired_cname_without_address():
    result = desired_records({"x.example.com"}, CNAME, cname_target="proxy.example.com")
    assert result == {Record(CNAME, "x.example.com", "proxy.example.com")}


def test_desired_cname_requires_target():
    with pytest.raises(ValueError):
        desired_records({"x"}, CNAME)


def test_adds_missing_records():
    plan = build_plan({a("x.example.com")}, set(), set(), {}, 3)
    assert plan.add == [a("x.example.com")]
    assert not plan.delete


def test_existing_identical_record_is_left_alone():
    plan = build_plan({a("x.example.com")}, {a("x.example.com")}, set(), {}, 3)
    assert plan.add == [] and plan.conflicts == set()


def test_foreign_record_blocks_name():
    existing = {a("x.example.com", "10.9.9.9")}
    plan = build_plan({a("x.example.com")}, existing, set(), {}, 3)
    assert plan.add == []
    assert plan.conflicts == {"x.example.com"}
    assert plan.delete == []


def test_foreign_cname_blocks_name():
    existing = {Record(CNAME, "x.example.com", "elsewhere.example.com")}
    plan = build_plan({a("x.example.com")}, existing, set(), {}, 3)
    assert plan.add == [] and plan.conflicts == {"x.example.com"}


def test_foreign_records_are_never_deleted():
    foreign = a("manual.example.com", "10.9.9.9")
    plan = build_plan(set(), {foreign}, set(), {}, 1)
    assert plan.delete == [] and plan.forget == []


def test_delete_waits_for_threshold():
    rec = a("old.example.com")
    missing = {}
    for count in (1, 2):
        plan = build_plan(set(), {rec}, {rec}, missing, 3)
        assert plan.delete == []
        assert plan.deferred == {rec: count}
        missing = plan.deferred
    plan = build_plan(set(), {rec}, {rec}, missing, 3)
    assert plan.delete == [rec]
    assert plan.deferred == {}


def test_reappearing_host_resets_counter():
    rec = a("flaky.example.com")
    plan = build_plan(set(), {rec}, {rec}, {}, 3)
    assert plan.deferred == {rec: 1}
    plan = build_plan({rec}, {rec}, {rec}, plan.deferred, 3)
    assert plan.deferred == {} and plan.delete == [] and plan.add == []


def test_managed_record_missing_in_pihole_is_forgotten():
    rec = a("gone.example.com")
    plan = build_plan(set(), set(), {rec}, {rec: 2}, 3)
    assert plan.forget == [rec] and plan.delete == []


def test_managed_record_missing_in_pihole_is_readded():
    rec = a("x.example.com")
    plan = build_plan({rec}, set(), {rec}, {}, 3)
    assert plan.add == [rec]


def test_changed_target_ip_replaces_immediately():
    old, new = a("x.example.com", "10.0.0.9"), a("x.example.com")
    plan = build_plan({new}, {old}, {old}, {}, 3)
    assert plan.delete == [old]
    assert plan.add == [new]
    assert plan.conflicts == set()


def test_switch_to_cname_replaces_managed_a_record():
    old = a("x.example.com")
    new = Record(CNAME, "x.example.com", "proxy.example.com")
    plan = build_plan({new}, {old}, {old}, {}, 3)
    assert plan.delete == [old] and plan.add == [new]
