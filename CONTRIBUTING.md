# Contributing to traefik-pihole-sync

Thanks for your interest! Bug reports, ideas and pull requests are welcome.

## Reporting problems

Use the issue forms: **Bug report** or **Feature request**. For bugs, please add the log
with `LOG_LEVEL=DEBUG`. German is fine too.

Security problems go to **Security → Report a vulnerability** instead, see
[SECURITY.md](SECURITY.md).

## Pull requests

1. Open an issue first for larger changes, so we can agree on the approach.
2. Set up the development environment and make sure all checks pass:

   ```bash
   python -m venv .venv && . .venv/bin/activate
   pip install -r requirements-dev.txt
   ruff check . && ruff format --check . && pytest
   ```

3. Keep the tool simple and safe: it must never delete or change DNS records it did not
   create itself.
4. Update README.md and README.de.md if needed and add a line under "Unreleased" in
   `CHANGELOG.md` if users will notice the change.

The pull request template has a short checklist for this.

## Code layout

| Path | Contents |
|---|---|
| `traefik_pihole_sync/config.py` | Environment variables and their validation |
| `traefik_pihole_sync/traefik.py` | Traefik API, rule parsing, domain filter |
| `traefik_pihole_sync/pihole.py` | Pi-hole v6 API client |
| `traefik_pihole_sync/plan.py` | Pure planning logic: what to add and delete |
| `traefik_pihole_sync/state.py` | State file and migration of the old format |
| `traefik_pihole_sync/main.py` | Sync loop, logging, health check, command line |
| `tests/` | Tests |

## License

By contributing you agree that your contribution is released under the
[MIT License](LICENSE).
