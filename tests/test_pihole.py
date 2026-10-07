import pytest
import responses

from traefik_pihole_sync.pihole import (
    PiholeClient,
    PiholeError,
    parse_cname_entry,
    parse_host_entry,
)
from traefik_pihole_sync.records import AAAA, CNAME, A, Record

URL = "http://pihole"
AUTH = {"session": {"valid": True, "sid": "abc", "csrf": "xyz", "validity": 1800}}


def client(password="secret", **kw):
    return PiholeClient(URL, password, max_retries=2, retry_delay=0, **kw)


def dns(key, entries):
    return {"config": {"dns": {key: entries}}}


def test_parse_host_entry():
    assert parse_host_entry("10.0.0.1 a.example.com") == [Record(A, "a.example.com", "10.0.0.1")]
    assert parse_host_entry("fd00::1 a.example.com") == [Record(AAAA, "a.example.com", "fd00::1")]
    assert parse_host_entry("10.0.0.1 a.example.com b.example.com") == [
        Record(A, "a.example.com", "10.0.0.1"),
        Record(A, "b.example.com", "10.0.0.1"),
    ]
    assert parse_host_entry("garbage") == []


def test_parse_cname_entry():
    assert parse_cname_entry("a.example.com,t.example.com") == [
        Record(CNAME, "a.example.com", "t.example.com")
    ]
    assert parse_cname_entry("a.example.com,t.example.com,300") == [
        Record(CNAME, "a.example.com", "t.example.com")
    ]
    assert parse_cname_entry("a.example.com,b.example.com,t.example.com") == [
        Record(CNAME, "a.example.com", "t.example.com"),
        Record(CNAME, "b.example.com", "t.example.com"),
    ]


@responses.activate
def test_get_records_authenticates_and_sends_sid():
    responses.post(f"{URL}/api/auth", json=AUTH)
    responses.get(
        f"{URL}/api/config/dns/hosts",
        json=dns("hosts", ["10.0.0.1 a.example.com"]),
        match=[responses.matchers.header_matcher({"X-FTL-SID": "abc"})],
    )
    responses.get(
        f"{URL}/api/config/dns/cnameRecords",
        json=dns("cnameRecords", ["b.example.com,a.example.com"]),
    )
    records = client().get_records()
    assert records == {
        Record(A, "a.example.com", "10.0.0.1"),
        Record(CNAME, "b.example.com", "a.example.com"),
    }


@responses.activate
def test_no_password_skips_auth():
    responses.get(f"{URL}/api/config/dns/hosts", json=dns("hosts", []))
    responses.get(f"{URL}/api/config/dns/cnameRecords", json=dns("cnameRecords", []))
    assert client(password="").get_records() == set()
    assert all("/api/auth" not in c.request.url for c in responses.calls)


@responses.activate
def test_no_password_but_auth_required():
    responses.get(f"{URL}/api/config/dns/hosts", status=401)
    with pytest.raises(PiholeError, match="authentication required"):
        client(password="").get_records()


@responses.activate
def test_wrong_password():
    responses.post(f"{URL}/api/auth", status=401, json={"error": {"key": "unauthorized"}})
    with pytest.raises(PiholeError, match="authentication failed"):
        client().get_records()


@responses.activate
def test_expired_session_reauthenticates():
    responses.post(f"{URL}/api/auth", json=AUTH)
    responses.get(f"{URL}/api/config/dns/hosts", status=401)
    responses.get(f"{URL}/api/config/dns/hosts", json=dns("hosts", []))
    responses.get(f"{URL}/api/config/dns/cnameRecords", json=dns("cnameRecords", []))
    assert client().get_records() == set()
    assert sum("/api/auth" in c.request.url for c in responses.calls) == 2


@responses.activate
def test_add_host_record_path():
    responses.post(f"{URL}/api/auth", json=AUTH)
    responses.put(f"{URL}/api/config/dns/hosts/10.0.0.1%20a.example.com", status=201)
    client().add_record(Record(A, "a.example.com", "10.0.0.1"))


@responses.activate
def test_add_cname_record_path():
    responses.post(f"{URL}/api/auth", json=AUTH)
    responses.put(f"{URL}/api/config/dns/cnameRecords/a.example.com%2Ct.example.com", status=201)
    client().add_record(Record(CNAME, "a.example.com", "t.example.com"))


@responses.activate
def test_add_already_present_is_success():
    responses.post(f"{URL}/api/auth", json=AUTH)
    responses.put(
        f"{URL}/api/config/dns/hosts/10.0.0.1%20a.example.com",
        status=400,
        json={"error": {"key": "bad_request", "message": "Invalid request: Item already present"}},
    )
    client().add_record(Record(A, "a.example.com", "10.0.0.1"))


@responses.activate
def test_add_other_error_raises():
    responses.post(f"{URL}/api/auth", json=AUTH)
    responses.put(
        f"{URL}/api/config/dns/hosts/10.0.0.1%20a.example.com",
        status=400,
        json={"error": {"key": "bad_request", "message": "Invalid hostname"}},
    )
    with pytest.raises(PiholeError, match="Invalid hostname"):
        client().add_record(Record(A, "a.example.com", "10.0.0.1"))


@responses.activate
def test_delete_missing_is_success():
    responses.post(f"{URL}/api/auth", json=AUTH)
    responses.delete(f"{URL}/api/config/dns/hosts/10.0.0.1%20a.example.com", status=404)
    client().delete_record(Record(A, "a.example.com", "10.0.0.1"))


@responses.activate
def test_rate_limit_is_retried():
    responses.post(f"{URL}/api/auth", json=AUTH)
    responses.put(
        f"{URL}/api/config/dns/hosts/10.0.0.1%20a.example.com",
        status=429,
        headers={"Retry-After": "0"},
    )
    responses.put(f"{URL}/api/config/dns/hosts/10.0.0.1%20a.example.com", status=201)
    client().add_record(Record(A, "a.example.com", "10.0.0.1"))


@responses.activate
def test_connection_error_gives_up():
    with pytest.raises(PiholeError, match="giving up"):
        client(password="").get_records()


@responses.activate
def test_logout():
    responses.post(f"{URL}/api/auth", json=AUTH)
    responses.get(f"{URL}/api/config/dns/hosts", json=dns("hosts", []))
    responses.get(f"{URL}/api/config/dns/cnameRecords", json=dns("cnameRecords", []))
    responses.delete(f"{URL}/api/auth", status=204)
    c = client()
    c.get_records()
    c.logout()
    assert responses.calls[-1].request.method == "DELETE"
    assert c.sid is None


def test_verify_tls_is_applied():
    assert client(verify_tls=False).session.verify is False
    assert client(verify_tls="/etc/ca.pem").session.verify == "/etc/ca.pem"
    assert client().session.verify is True


@responses.activate
def test_redirect_is_not_followed():
    responses.post(
        f"{URL}/api/auth",
        status=307,
        headers={"Location": "https://elsewhere.example.net/api/auth"},
    )
    responses.post("https://elsewhere.example.net/api/auth", json=AUTH)
    with pytest.raises(PiholeError, match="redirects to https://elsewhere.example.net"):
        client().get_records()
    assert all("elsewhere" not in c.request.url for c in responses.calls)


@responses.activate
def test_retry_after_is_capped(monkeypatch):
    waits = []
    monkeypatch.setattr("traefik_pihole_sync.pihole.time.sleep", waits.append)
    responses.post(f"{URL}/api/auth", json=AUTH)
    responses.put(
        f"{URL}/api/config/dns/hosts/10.0.0.1%20a.example.com",
        status=429,
        headers={"Retry-After": "999999"},
    )
    responses.put(f"{URL}/api/config/dns/hosts/10.0.0.1%20a.example.com", status=201)
    client().add_record(Record(A, "a.example.com", "10.0.0.1"))
    assert waits == [300.0]
