"""Property-based tests with random input (Hypothesis).

They check the promises the tool makes regardless of what Traefik or Pi-hole send:
hostnames from rules are always valid, parsing never crashes, nothing outside DOMAINS is
written, and records the tool did not create are never touched.
"""

from __future__ import annotations

import string

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from traefik_pihole_sync import pihole, traefik
from traefik_pihole_sync.plan import build_plan
from traefik_pihole_sync.records import A, Record

FUZZ = settings(max_examples=2000, deadline=None, suppress_health_check=list(HealthCheck))

# Pieces of Traefik rules, so the random rules look like real ones often enough
RULE_PIECES = [*'Host()SNI`"!&|, .-*{}abcxyz0123456789\\\n\t', "Host(", "HostSNI(", "&&", "||"]
rules = st.lists(st.sampled_from(RULE_PIECES), max_size=200).map("".join)


@FUZZ
@given(st.one_of(rules, st.text(max_size=300)), st.sampled_from(["Host", "HostSNI"]))
def test_extract_hosts_returns_only_valid_hostnames(rule, matcher):
    for host in traefik.extract_hosts(rule, matcher):
        assert traefik.is_valid_hostname(host), host
        assert "*" not in host
        assert "{" not in host


@FUZZ
@given(st.text(max_size=200))
def test_pihole_entries_never_crash(entry):
    for record in pihole.parse_host_entry(entry) + pihole.parse_cname_entry(entry):
        assert isinstance(record, Record)


hostnames = st.text(alphabet=string.ascii_lowercase + string.digits + ".-", max_size=30)
domains = st.text(alphabet=string.ascii_lowercase + ".", min_size=1, max_size=15)


@FUZZ
@given(st.lists(hostnames, max_size=20), st.lists(domains, max_size=4), st.booleans())
def test_filter_hosts_stays_inside_domains(names, raw_domains, include_apex):
    wanted = tuple(sorted({d.strip(".") for d in raw_domains if d.strip(".")}))
    result = traefik.filter_hosts(names, wanted, include_apex)
    if wanted:
        for host in result:
            assert traefik.domain_of(host, wanted) is not None, (host, wanted)


names = st.sampled_from(["a.example.com", "b.example.com", "c.example.com"])
addresses = st.sampled_from(["192.0.2.1", "192.0.2.2"])
records = st.builds(lambda name, ip: Record(A, name, ip), names, addresses)


@FUZZ
@given(st.data())
def test_plan_never_touches_foreign_records(data):
    desired = data.draw(st.sets(records))
    existing = data.draw(st.sets(records))
    managed = data.draw(st.sets(records))
    missing = {r: data.draw(st.integers(0, 5)) for r in managed}
    plan = build_plan(desired, existing, managed, missing, data.draw(st.integers(1, 4)))

    # Only records the tool created are deleted or forgotten
    assert set(plan.delete) <= managed
    assert set(plan.forget) <= managed
    # Nothing is added to a name that carries records the tool did not create
    foreign = {r.name for r in existing if r not in managed and r not in desired}
    assert not {r.name for r in plan.add} & foreign
