# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Report them privately through
GitHub instead: on the repository page open **Security → Report a vulnerability**. You will
get an answer within a few days, and a fix is released as soon as possible.

If that option is not shown, contact the maintainer [@Schnuecks](https://github.com/Schnuecks)
through GitHub and ask for a private channel, without describing the problem publicly.

Helpful details: the traefik-pihole-sync version (first log line or `--version`), how
Traefik and Pi-hole are reached (HTTP or HTTPS, same host or network) and the steps to
reproduce.

## Supported versions

Security fixes go into the latest release. Please update to it before reporting.

## Scope

traefik-pihole-sync has no network listener of its own. It reads the Traefik API and
writes local DNS records through the Pi-hole API.

- The Pi-hole password is read from the environment or, preferably, from a file
  (`PIHOLE_PASSWORD_FILE`, e.g. a Docker secret). It is never logged.
- TLS certificates of HTTPS Pi-hole URLs are verified unless you set
  `PIHOLE_VERIFY_TLS=false`.
- The container runs as an unprivileged user (UID 10001).
- Anyone who can create Traefik routers can create DNS names in your network through this
  tool, but only names inside `DOMAINS` and only pointing at your configured target. Set
  `DOMAINS` if untrusted parties can add routers.
