import pytest

from traefik_pihole_sync.config import ConfigError, load

BASE = {"PIHOLE_URL": "http://pihole", "TARGET_IP": "10.0.0.1"}


def env(**kw):
    return {**BASE, **kw}


def test_defaults():
    cfg = load(BASE)
    assert cfg.record_type == "A"
    assert cfg.verify_tls is True
    assert cfg.include_apex is False
    assert cfg.domains == ()
    assert cfg.piholes[0].url == "http://pihole"
    assert cfg.piholes[0].password == ""
    assert cfg.health_max_age == 300


def test_pihole_url_required():
    with pytest.raises(ConfigError):
        load({"TARGET_IP": "10.0.0.1"})


def test_a_mode_needs_an_address():
    with pytest.raises(ConfigError):
        load({"PIHOLE_URL": "http://pihole"})
    assert load({"PIHOLE_URL": "http://p", "TARGET_IPV6": "fd00::1"}).target_ipv6 == "fd00::1"


def test_invalid_ips():
    with pytest.raises(ConfigError):
        load(env(TARGET_IP="300.1.1.1"))
    with pytest.raises(ConfigError):
        load(env(TARGET_IP="fd00::1"))
    with pytest.raises(ConfigError):
        load(env(TARGET_IPV6="10.0.0.1"))


def test_cname_mode():
    cfg = load(
        {"PIHOLE_URL": "http://p", "RECORD_TYPE": "cname", "CNAME_TARGET": "Proxy.Example.com."}
    )
    assert cfg.record_type == "CNAME"
    assert cfg.cname_target == "proxy.example.com"
    assert cfg.target_ip is None
    with pytest.raises(ConfigError):
        load({"PIHOLE_URL": "http://p", "RECORD_TYPE": "CNAME"})


def test_invalid_record_type():
    with pytest.raises(ConfigError):
        load(env(RECORD_TYPE="TXT"))


def test_domains_and_legacy_allowed_zone():
    assert load(env(DOMAINS="Example.com, .lab.example.org")).domains == (
        "example.com",
        "lab.example.org",
    )
    assert load(env(ALLOWED_ZONE="example.com")).domains == ("example.com",)
    assert load(env(DOMAINS="a.com", ALLOWED_ZONE="b.com")).domains == ("a.com",)


def test_multiple_piholes_single_password():
    cfg = load(env(PIHOLE_URL="http://a/, http://b", PIHOLE_PASSWORD="secret"))
    assert [p.url for p in cfg.piholes] == ["http://a", "http://b"]
    assert [p.password for p in cfg.piholes] == ["secret", "secret"]


def test_multiple_piholes_password_list():
    cfg = load(env(PIHOLE_URL="http://a,http://b", PIHOLE_PASSWORD="one,two"))
    assert [p.password for p in cfg.piholes] == ["one", "two"]


def test_password_with_comma_and_mismatching_count_is_single():
    cfg = load(env(PIHOLE_URL="http://a,http://b", PIHOLE_PASSWORD="x,y,z"))
    assert [p.password for p in cfg.piholes] == ["x,y,z", "x,y,z"]


def test_duplicate_urls():
    with pytest.raises(ConfigError):
        load(env(PIHOLE_URL="http://a,http://a/"))


def test_password_files(tmp_path):
    f1, f2 = tmp_path / "one", tmp_path / "two"
    f1.write_text("first\n")
    f2.write_text("second\n")
    cfg = load(env(PIHOLE_URL="http://a,http://b", PIHOLE_PASSWORD_FILE=f"{f1},{f2}"))
    assert [p.password for p in cfg.piholes] == ["first", "second"]
    cfg = load(env(PIHOLE_URL="http://a,http://b", PIHOLE_PASSWORD_FILE=str(f1)))
    assert [p.password for p in cfg.piholes] == ["first", "first"]
    # An empty entry means "no authentication" for that Pi-hole.
    cfg = load(env(PIHOLE_URL="http://a,http://b", PIHOLE_PASSWORD_FILE=f"{f1},"))
    assert [p.password for p in cfg.piholes] == ["first", ""]


def test_password_file_count_mismatch(tmp_path):
    f = tmp_path / "pw"
    f.write_text("x")
    with pytest.raises(ConfigError):
        load(env(PIHOLE_URL="http://a,http://b,http://c", PIHOLE_PASSWORD_FILE=f"{f},{f}"))


def test_missing_password_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError):
        load(env(PIHOLE_PASSWORD_FILE=str(tmp_path / "missing")))


def test_legacy_password_variables(tmp_path):
    f = tmp_path / "pw"
    f.write_text("legacy\n")
    assert load(env(PIHOLE_APP_PASSWORD_FILE=str(f))).piholes[0].password == "legacy"
    assert load(env(PIHOLE_APP_PASSWORD="old")).piholes[0].password == "old"
    assert load(env(PIHOLE_APP_PASSWORD="old", PIHOLE_PASSWORD="new")).piholes[0].password == "new"


def test_password_not_in_repr():
    cfg = load(env(PIHOLE_PASSWORD="topsecret"))
    assert "topsecret" not in repr(cfg)


def test_verify_tls(tmp_path):
    assert load(env(PIHOLE_VERIFY_TLS="false")).verify_tls is False
    assert load(env(PIHOLE_VERIFY_TLS="TRUE")).verify_tls is True
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy")
    assert load(env(PIHOLE_VERIFY_TLS=str(ca))).verify_tls == str(ca)
    with pytest.raises(ConfigError):
        load(env(PIHOLE_VERIFY_TLS="/does/not/exist.pem"))


def test_bools_and_ints():
    cfg = load(env(INCLUDE_APEX="yes", DRY_RUN="1", TRAEFIK_TCP_ROUTERS="on", SYNC_INTERVAL="120"))
    assert cfg.include_apex and cfg.dry_run and cfg.tcp_routers
    assert cfg.interval == 120
    assert cfg.health_max_age == 360
    with pytest.raises(ConfigError):
        load(env(DRY_RUN="maybe"))
    with pytest.raises(ConfigError):
        load(env(SYNC_INTERVAL="0"))
    with pytest.raises(ConfigError):
        load(env(DELETE_THRESHOLD="abc"))
