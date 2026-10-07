# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## 1.0.0

First stable release.

### Features
- Reads `Host()` rules of Traefik HTTP routers, optionally `HostSNI()` rules of TCP routers
  (`TRAEFIK_TCP_ROUTERS`), with every page of the Traefik API. `Host()` matchers with several
  values (Traefik v2) and double-quoted values are supported.
- A records (`TARGET_IP`), AAAA records (`TARGET_IPV6`) or CNAME records
  (`RECORD_TYPE=CNAME` with `CNAME_TARGET`, optionally with an A/AAAA record for the target
  itself).
- Several Pi-hole instances in `PIHOLE_URL`, with one password for all or one per instance,
  and a separate state per instance. Instances without a password skip authentication.
- `DOMAINS` filter for one or more domains; `INCLUDE_APEX` adds the matching domain itself,
  so multi-part suffixes such as `.co.uk` work.
- Only records the tool created are ever deleted; names with records it did not create are
  left alone. Deletion waits `DELETE_THRESHOLD` cycles; a changed target is replaced at once.
  `DRY_RUN=true` logs changes without writing anything.
- `PIHOLE_VERIFY_TLS` (`true`, `false` or a CA bundle path); TLS is verified by default.
- Built-in health check (`--healthcheck`) and `--once` for a single run.
- Container runs as a non-root user; images for amd64 and arm64.

### Security
- Requests to Pi-hole do not follow redirects, so the session ID and the password can never
  be sent to another address. A redirect is reported as an error.
- A `Retry-After` header from Pi-hole is capped at 300 seconds.
- A damaged state file stops the tool with a clear message instead of a traceback.

### Deprecated
- `ALLOWED_ZONE` (use `DOMAINS`), `PIHOLE_APP_PASSWORD` and `PIHOLE_APP_PASSWORD_FILE`
  (use `PIHOLE_PASSWORD` and `PIHOLE_PASSWORD_FILE`). They still work, and an old
  `managed_hosts.json` state file is migrated automatically.
