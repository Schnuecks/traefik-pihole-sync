import pytest
import responses

from traefik_pihole_sync.traefik import TraefikClient, extract_hosts, filter_hosts


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("Host(`a.example.com`)", {"a.example.com"}),
        ("Host(`A.Example.com`) && PathPrefix(`/api`)", {"a.example.com"}),
        ("Host(`a.example.com`,`b.example.com`)", {"a.example.com", "b.example.com"}),
        ("Host(`a.example.com`, `b.example.com`)", {"a.example.com", "b.example.com"}),
        ('Host("a.example.com")', {"a.example.com"}),
        ("Host(`a.example.com`) || Host(`b.example.com`)", {"a.example.com", "b.example.com"}),
        (r"HostRegexp(`^.+\.example\.com$`)", set()),
        ("HostRegexp(`{sub:[a-z]+}.example.com`)", set()),
        ("Host(`*.example.com`)", set()),
        ("Host(`{name}.example.com`)", set()),
        ("Host(`a.example.com`) && !Host(`b.example.com`)", {"a.example.com"}),
        ("PathPrefix(`/`)", set()),
        ("", set()),
        ("Host(`not a host`)", set()),
        ("Host(`a.example.com.`)", {"a.example.com"}),
    ],
)
def test_extract_hosts(rule, expected):
    assert extract_hosts(rule) == expected


def test_extract_hostsni():
    assert extract_hosts("HostSNI(`db.example.com`)", "HostSNI") == {"db.example.com"}
    assert extract_hosts("HostSNI(`*`)", "HostSNI") == set()
    assert extract_hosts("HostSNIRegexp(`^.+$`)", "HostSNI") == set()
    # A Host() matcher in an HTTP rule is not a HostSNI matcher.
    assert extract_hosts("Host(`a.example.com`)", "HostSNI") == set()


def test_filter_hosts_without_domains_keeps_everything():
    assert filter_hosts({"a.example.com", "b.other"}, (), True) == {"a.example.com", "b.other"}


def test_filter_hosts_by_domain():
    hosts = {"a.example.com", "b.example.org", "example.com.evil"}
    assert filter_hosts(hosts, ("example.com",), False) == {"a.example.com"}


def test_apex_uses_configured_domain():
    hosts = {"app.home.example.co.uk", "x.example.com"}
    result = filter_hosts(hosts, ("home.example.co.uk", "example.com"), True)
    assert result == {
        "app.home.example.co.uk",
        "home.example.co.uk",
        "x.example.com",
        "example.com",
    }


def test_apex_prefers_longest_domain():
    result = filter_hosts({"a.lab.example.com"}, ("example.com", "lab.example.com"), True)
    assert result == {"a.lab.example.com", "lab.example.com"}


BASE = "http://traefik:8080"


@responses.activate
def test_pagination_follows_next_page():
    page1 = [{"name": f"r{i}", "rule": f"Host(`h{i}.example.com`)"} for i in range(100)]
    page2 = [{"name": "last", "rule": "Host(`last.example.com`)"}]
    responses.get(
        f"{BASE}/api/http/routers?page=1&per_page=100", json=page1, headers={"X-Next-Page": "2"}
    )
    responses.get(
        f"{BASE}/api/http/routers?page=2&per_page=100", json=page2, headers={"X-Next-Page": "1"}
    )
    hosts = TraefikClient(BASE).get_hostnames()
    assert hosts == {f"h{i}.example.com" for i in range(100)} | {"last.example.com"}


@responses.activate
def test_single_page_without_header():
    responses.get(f"{BASE}/api/http/routers", json=[{"rule": "Host(`a.example.com`)"}])
    assert TraefikClient(BASE).get_hostnames() == {"a.example.com"}


@responses.activate
def test_tcp_routers():
    responses.get(f"{BASE}/api/http/routers", json=[{"rule": "Host(`a.example.com`)"}])
    responses.get(f"{BASE}/api/tcp/routers", json=[{"rule": "HostSNI(`db.example.com`)"}])
    client = TraefikClient(BASE)
    assert client.get_hostnames(tcp=True) == {"a.example.com", "db.example.com"}


@responses.activate
def test_error_is_raised():
    responses.get(f"{BASE}/api/http/routers", status=500)
    with pytest.raises(Exception):  # noqa: B017
        TraefikClient(BASE).get_hostnames()
