<p align="center"><img src="docs/logo.svg" width="96" alt="traefik-pihole-sync"></p>

# traefik-pihole-sync

**English** · [Deutsch](README.de.md)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <a href="https://github.com/Schnuecks/traefik-pihole-sync/pkgs/container/traefik-pihole-sync"><img src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker ready"></a>
  <img src="https://img.shields.io/badge/platform-amd64%20%7C%20arm64-E4572E" alt="Platform amd64 | arm64">
  <img src="https://img.shields.io/badge/Traefik-v2%20%7C%20v3-24A1C1?logo=traefikproxy&logoColor=white" alt="Traefik v2 | v3">
  <img src="https://img.shields.io/badge/Pi--hole-v6-96060C?logo=pihole&logoColor=white" alt="Pi-hole v6">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-4C9A2A" alt="License MIT"></a>
  <img src="https://img.shields.io/badge/maintained-yes-4C9A2A" alt="Maintained">
</p>

Keeps the local DNS records of [Pi-hole v6](https://pi-hole.net/) in sync with the hostnames
of your [Traefik](https://traefik.io/) routers. Start a container with a `Host()` rule and its
name resolves on your network a minute later; remove it and the record goes away again.

## Features

- **Reads Traefik routers:** `Host()` rules of HTTP routers, optionally `HostSNI()` rules of
  TCP routers, with every page of the Traefik API
- **A, AAAA or CNAME records:** point hostnames at an IPv4 and/or IPv6 address, or make
  them CNAMEs of your proxy host
- **Several Pi-holes** at once, each with its own password and state
- **Safe by design:** only deletes records it created itself, never touches names you
  manage by hand, waits a few cycles before deleting and has a dry-run mode
- **Domain filter** for one or more domains, optionally with the apex record
- **Quiet logs:** changes and problems at `INFO`, a status line per hour, repeated errors
  only once
- **Small container:** runs as a non-root user, built-in health check, images for amd64
  and arm64, logs out of Pi-hole on shutdown

## How it works

Every `SYNC_INTERVAL` seconds the tool

1. reads all routers from the Traefik API (all pages) and extracts the literal hostnames
   from `Host()` (and `HostSNI()`) rules; wildcards, `HostRegexp` and placeholders are skipped,
2. keeps only hostnames inside `DOMAINS`,
3. builds the desired records: `<host> → TARGET_IP` (and `TARGET_IPV6`), or
   `<host> CNAME CNAME_TARGET`,
4. compares them with each Pi-hole and adds what is missing.

It remembers every record it created in a state file. These rules keep it from damaging
records you manage yourself:

- **Records it did not create are never deleted.**
- **Names that already have records it did not create are left alone.** It logs one
  warning per name and skips it.
- **Deletion is delayed.** A record is deleted only after its host was missing from Traefik
  `DELETE_THRESHOLD` cycles in a row. A restarting container does not cause DNS flapping.
  If the host still exists but its target changed (e.g. a new `TARGET_IP`), the old
  record is replaced right away.
- `DRY_RUN=true` logs what would change without writing anything.

## Quick start

```yaml
services:
  traefik-pihole-sync:
    image: ghcr.io/schnuecks/traefik-pihole-sync:latest
    container_name: traefik-pihole-sync
    restart: unless-stopped
    environment:
      TRAEFIK_API_URL: http://traefik:8080
      PIHOLE_URL: https://pihole.example.com
      PIHOLE_PASSWORD_FILE: /run/secrets/pihole_password
      TARGET_IP: 192.0.2.10          # the IP of your Traefik host
      DOMAINS: example.com
    secrets:
      - pihole_password
    volumes:
      - ./data:/data
    networks:
      - proxy                        # a network that can reach Traefik's API

secrets:
  pihole_password:
    file: ./secrets/pihole_password.txt

networks:
  proxy:
    external: true
```

The container runs as UID `10001`. A bind-mounted `./data` directory must be writable for
it:

```bash
mkdir -p data && sudo chown 10001 data
```

Named volumes need no extra step. File-based Compose secrets keep the owner and mode of
the file on the host, so the secret file must be readable for UID `10001` as well. Either
`sudo chown 10001 secrets/pihole_password.txt` (mode `600` is fine), or run the container
as your own user with `user: "1000:1000"` and make `./data` writable for that user.

Run once with `DRY_RUN=true` and check the log before you let it write.

## Preparing Pi-hole

The tool talks to the Pi-hole v6 REST API. Use an **app password** rather than your web
interface password:

1. In the Pi-hole web interface switch the settings pages to **Expert** mode (toggle in the
   top right corner of any settings page).
2. Open **Settings → All settings → Webserver and API** and enable
   `webserver.api.app_sudo`. Without it, sessions opened with an app password may read but
   not change the configuration.
3. Open **Settings → Web interface / API**, click **Configure app password**, copy the
   generated password and apply it.
4. Put the password into the secret file (`./secrets/pihole_password.txt` above). It must
   contain only the password.

The password is sent to Pi-hole when the tool logs in. Use an `https://` URL unless Pi-hole
runs on the same host or in a network you trust. Redirects are never followed, so give
the final address in `PIHOLE_URL`.

If your Pi-hole has no password at all, leave `PIHOLE_PASSWORD`/`PIHOLE_PASSWORD_FILE`
empty. The tool then skips authentication.

On shutdown (`docker stop` sends SIGTERM) the tool logs out of Pi-hole, so restarts do not
pile up open API sessions.

## Giving access to the Traefik API

The tool needs read access to `/api/http/routers` (and `/api/tcp/routers` with
`TRAEFIK_TCP_ROUTERS=true`). The simplest setup enables the API on Traefik's internal port
8080 and keeps that port **off** the host:

```yaml
services:
  traefik:
    command:
      - --api=true
      - --api.insecure=true   # serves the API on the "traefik" entrypoint, port 8080
    # do not publish 8080 under "ports:"
    networks:
      - proxy
```

`traefik-pihole-sync` joins the same Docker network and uses
`TRAEFIK_API_URL=http://traefik:8080`. If you already expose the dashboard through a
router, you can point `TRAEFIK_API_URL` at it instead, as long as the URL can be reached
without interactive login.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TRAEFIK_API_URL` | `http://traefik:8080` | Base URL of the Traefik API |
| `TRAEFIK_TCP_ROUTERS` | `false` | Also read TCP routers (`HostSNI()` rules) |
| `PIHOLE_URL` | – (required) | Pi-hole base URL; comma-separated for several instances |
| `PIHOLE_PASSWORD_FILE` | – | File with the app password; a comma-separated list assigns one file per instance |
| `PIHOLE_PASSWORD` | – | App password; one value for all, or a comma-separated list with one value per instance |
| `PIHOLE_VERIFY_TLS` | `true` | `true`, `false` or the path of a CA bundle for HTTPS Pi-hole URLs |
| `RECORD_TYPE` | `A` | `A` or `CNAME` |
| `TARGET_IP` | – | IPv4 address for A records. Required in A mode unless `TARGET_IPV6` is set |
| `TARGET_IPV6` | – | IPv6 address; adds AAAA records |
| `CNAME_TARGET` | – | CNAME target (required with `RECORD_TYPE=CNAME`) |
| `DOMAINS` | – (all) | Comma-separated domains; only hostnames inside them are synced |
| `INCLUDE_APEX` | `false` | Also create a record for each domain in `DOMAINS` that has at least one hostname |
| `SYNC_INTERVAL` | `60` | Seconds between sync cycles |
| `DELETE_THRESHOLD` | `3` | Cycles a host must be missing before its record is deleted |
| `DRY_RUN` | `false` | Log changes without writing them |
| `STATE_FILE` | `/data/state.json` | Where the list of created records is stored |
| `HEALTH_FILE` | `/tmp/traefik-pihole-sync.health` | Touched after every successful cycle |
| `HEALTH_MAX_AGE` | `max(300, 3 × SYNC_INTERVAL)` | Seconds after which the health check fails |
| `HEARTBEAT` | `3600` | Seconds between status lines in the log; `0` disables them |
| `WRITE_DELAY` | `0.5` | Seconds to wait after each write (each write restarts Pi-hole's DNS resolver) |
| `MAX_RETRIES` | `5` | Attempts per Pi-hole request on connection errors or rate limiting |
| `REQUEST_TIMEOUT` | `10` | HTTP timeout in seconds |
| `LOG_LEVEL` | `INFO` | `DEBUG` shows every router and every comparison |

Passwords that contain a comma: use `PIHOLE_PASSWORD_FILE`, or `PIHOLE_PASSWORD` with a
single Pi-hole.

### CNAME mode

```yaml
RECORD_TYPE: CNAME
CNAME_TARGET: proxy.example.com
TARGET_IP: 192.0.2.10   # optional: also creates proxy.example.com → 192.0.2.10
```

Every hostname becomes `<host> CNAME proxy.example.com`. If the IP of your proxy changes,
only one record has to change. Pi-hole can only resolve the CNAME if it knows the target,
so either set `TARGET_IP`/`TARGET_IPV6` or create the target record yourself.

### Several Pi-holes

```yaml
PIHOLE_URL: https://pihole1.example.com,https://pihole2.example.com
PIHOLE_PASSWORD_FILE: /run/secrets/pihole1,/run/secrets/pihole2
```

Each instance is compared and updated on its own, with its own part of the state file.
If one instance is down, the others are still updated. If you already replicate local DNS
records between your Pi-holes with another tool, list only the primary here.

## Logging and health

Routine work is logged at `DEBUG`. At `INFO` you see changes, warnings and one status line
per hour. A source that keeps failing (Traefik or a Pi-hole) is reported once, and its
recovery once.

The image has a `HEALTHCHECK`. It runs `python -m traefik_pihole_sync --healthcheck` and
reports unhealthy if the last fully successful cycle is older than `HEALTH_MAX_AGE`.

```bash
docker run --rm ghcr.io/schnuecks/traefik-pihole-sync:latest --version
docker compose run --rm traefik-pihole-sync --once   # one cycle, then exit
```

## Upgrading from earlier versions

Earlier versions (a single-file script) kept a list of hostnames in `/data/managed_hosts.json`.
On the first start with a new `/data/state.json`, that file is migrated automatically. Its
hostnames become A records with `TARGET_IP` for the **first** Pi-hole in `PIHOLE_URL`.
The old file is left in place. The old variable names `ALLOWED_ZONE`,
`PIHOLE_APP_PASSWORD` and `PIHOLE_APP_PASSWORD_FILE` still work.

Differences to watch out for:

- `INCLUDE_APEX` now defaults to `false`. Set it to `true` if you relied on it.
- The container no longer runs as root. Fix the ownership of the data directory (see above).
- TLS certificates are verified. For a self-signed Pi-hole certificate set
  `PIHOLE_VERIFY_TLS` to your CA file or to `false`.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && pytest
```

## Support

traefik-pihole-sync is free and stays free. If it saves you time, you can buy me a coffee
or send something via PayPal; it keeps the project going. Thank you!

<p>
  <a href="https://buymeacoffee.com/il6hhwtzr6"><img src="https://img.shields.io/badge/Buy_me_a_coffee-10_%E2%82%AC-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy me a coffee: 10 €"></a>
  <a href="https://buymeacoffee.com/il6hhwtzr6"><img src="https://img.shields.io/badge/Buy_me_a_coffee-25_%E2%82%AC-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy me a coffee: 25 €"></a>
  <a href="https://buymeacoffee.com/il6hhwtzr6"><img src="https://img.shields.io/badge/Buy_me_a_coffee-50_%E2%82%AC-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy me a coffee: 50 €"></a>
</p>

<p>
  <a href="https://paypal.me/Schnuecks/10EUR"><img src="https://img.shields.io/badge/PayPal-10_%E2%82%AC-00457C?logo=paypal&logoColor=white" alt="PayPal: 10 €"></a>
  <a href="https://paypal.me/Schnuecks/25EUR"><img src="https://img.shields.io/badge/PayPal-25_%E2%82%AC-00457C?logo=paypal&logoColor=white" alt="PayPal: 25 €"></a>
  <a href="https://paypal.me/Schnuecks/50EUR"><img src="https://img.shields.io/badge/PayPal-50_%E2%82%AC-00457C?logo=paypal&logoColor=white" alt="PayPal: 50 €"></a>
</p>

## Feedback

Bug reports and ideas are welcome as
[GitHub issues](https://github.com/Schnuecks/traefik-pihole-sync/issues). For bugs, please
include the log with `LOG_LEVEL=DEBUG`; replace hostnames and addresses you do not want
to share. See also [CONTRIBUTING](CONTRIBUTING.md) and [SECURITY](SECURITY.md).

What changed in each version is listed in the [CHANGELOG](CHANGELOG.md).

## License

Copyright (c) 2026 Schnuecks. Released under the [MIT License](LICENSE).

This project is not affiliated with or endorsed by Traefik Labs or Pi-hole LLC. Traefik
and Pi-hole are trademarks of their respective owners.
