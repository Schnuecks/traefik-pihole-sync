<p align="center"><img src="docs/logo.svg" width="96" alt="traefik-pihole-sync"></p>

# traefik-pihole-sync

[English](README.md) · **Deutsch**

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <a href="https://github.com/Schnuecks/traefik-pihole-sync/pkgs/container/traefik-pihole-sync"><img src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker ready"></a>
  <img src="https://img.shields.io/badge/platform-amd64%20%7C%20arm64-E4572E" alt="Platform amd64 | arm64">
  <img src="https://img.shields.io/badge/Traefik-v2%20%7C%20v3-24A1C1?logo=traefikproxy&logoColor=white" alt="Traefik v2 | v3">
  <img src="https://img.shields.io/badge/Pi--hole-v6-96060C?logo=pihole&logoColor=white" alt="Pi-hole v6">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-4C9A2A" alt="License MIT"></a>
  <img src="https://img.shields.io/badge/maintained-yes-4C9A2A" alt="Maintained">
</p>

Hält die lokalen DNS-Einträge von [Pi-hole v6](https://pi-hole.net/) mit den Hostnamen deiner
[Traefik](https://traefik.io/)-Router synchron. Startest du einen Container mit einer
`Host()`-Regel, ist sein Name eine Minute später in deinem Netz auflösbar. Entfernst du ihn,
verschwindet auch der Eintrag wieder.

## Funktionen

- **Liest Traefik-Router:** `Host()`-Regeln von HTTP-Routern, auf Wunsch auch
  `HostSNI()`-Regeln von TCP-Routern, über alle Seiten der Traefik-API
- **A-, AAAA- oder CNAME-Einträge:** Hostnamen zeigen auf eine IPv4- und/oder IPv6-Adresse
  oder werden CNAMEs deines Proxy-Hosts
- **Mehrere Pi-holes** gleichzeitig, jedes mit eigenem Passwort und eigenem State
- **Sicher gebaut:** löscht nur Einträge, die es selbst angelegt hat, fasst von Hand
  gepflegte Namen nie an, wartet vor dem Löschen einige Durchläufe ab und hat einen
  Probelauf-Modus
- **Domainfilter** für eine oder mehrere Domains, auf Wunsch mit Eintrag für die Domain selbst
- **Ruhige Logs:** Änderungen und Probleme auf `INFO`, eine Statuszeile pro Stunde,
  wiederholte Fehler nur einmal
- **Schlanker Container:** läuft ohne Root-Rechte, eingebauter Healthcheck, Images für
  amd64 und arm64, meldet sich beim Beenden von Pi-hole ab

## So funktioniert es

Alle `SYNC_INTERVAL` Sekunden

1. liest das Tool alle Router aus der Traefik-API (alle Seiten) und holt die festen
   Hostnamen aus `Host()`- (und `HostSNI()`-)Regeln; Platzhalter, `HostRegexp` und `*`
   werden übersprungen,
2. behält nur Hostnamen innerhalb von `DOMAINS`,
3. bildet daraus die gewünschten Einträge: `<host> → TARGET_IP` (und `TARGET_IPV6`) oder
   `<host> CNAME CNAME_TARGET`,
4. vergleicht sie mit jedem Pi-hole und ergänzt, was fehlt.

Jeden angelegten Eintrag merkt es sich in einer State-Datei. Diese Regeln schützen deine
eigenen Einträge:

- **Einträge, die es nicht selbst angelegt hat, werden nie gelöscht.**
- **Namen, für die es schon fremde Einträge gibt, bleiben unangetastet.** Es warnt einmal
  pro Name und überspringt ihn.
- **Löschen erfolgt verzögert.** Ein Eintrag wird erst gelöscht, wenn sein Host
  `DELETE_THRESHOLD` Durchläufe in Folge in Traefik gefehlt hat. Ein neu startender
  Container lässt DNS also nicht flackern. Gibt es den Host noch, aber mit neuem Ziel
  (z. B. neue `TARGET_IP`), wird der alte Eintrag sofort ersetzt.
- `DRY_RUN=true` protokolliert nur, was sich ändern würde, und schreibt nichts.

## Schnellstart

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
      TARGET_IP: 192.0.2.10          # die IP deines Traefik-Hosts
      DOMAINS: example.com
    secrets:
      - pihole_password
    volumes:
      - ./data:/data
    networks:
      - proxy                        # ein Netz, in dem die Traefik-API erreichbar ist

secrets:
  pihole_password:
    file: ./secrets/pihole_password.txt

networks:
  proxy:
    external: true
```

Der Container läuft mit der UID `10001`. Ein eingebundenes Verzeichnis `./data` muss für sie
beschreibbar sein:

```bash
mkdir -p data && sudo chown 10001 data
```

Benannte Volumes brauchen keinen zusätzlichen Schritt. Secrets aus Dateien übernimmt Compose
mit Besitzer und Rechten vom Host, die Secret-Datei muss für die UID `10001` also ebenfalls
lesbar sein. Entweder `sudo chown 10001 secrets/pihole_password.txt` (Rechte `600` passen),
oder du lässt den Container mit `user: "1000:1000"` als deinen eigenen Benutzer laufen und
machst `./data` für diesen beschreibbar.

Starte zuerst mit `DRY_RUN=true` und prüfe das Log, bevor du es schreiben lässt.

## Pi-hole vorbereiten

Das Tool spricht mit der REST-API von Pi-hole v6. Nimm dafür ein **App-Passwort** statt
deines Passworts für die Weboberfläche:

1. Stelle in der Pi-hole-Weboberfläche die Einstellungsseiten auf **Expert** um (Schalter
   oben rechts auf jeder Einstellungsseite).
2. Öffne **Settings → All settings → Webserver and API** und aktiviere
   `webserver.api.app_sudo`. Ohne diese Option dürfen Sitzungen mit App-Passwort die
   Konfiguration zwar lesen, aber nicht ändern.
3. Öffne **Settings → Web interface / API**, klicke auf **Configure app password**,
   kopiere das erzeugte Passwort und übernimm es.
4. Schreibe das Passwort in die Secret-Datei (oben `./secrets/pihole_password.txt`). Sie
   darf nur das Passwort enthalten.

Das Passwort geht bei der Anmeldung an Pi-hole über das Netz. Nutze eine `https://`-URL, es
sei denn, Pi-hole läuft auf demselben Host oder in einem Netz, dem du vertraust.
Weiterleitungen folgt das Tool nie; gib in `PIHOLE_URL` also die endgültige Adresse an.

Hat dein Pi-hole gar kein Passwort, lass `PIHOLE_PASSWORD`/`PIHOLE_PASSWORD_FILE` leer.
Das Tool überspringt dann die Anmeldung.

Beim Beenden (`docker stop` sendet SIGTERM) meldet sich das Tool bei Pi-hole ab. So sammeln
sich bei Neustarts keine offenen API-Sitzungen an.

## Zugriff auf die Traefik-API

Das Tool braucht Lesezugriff auf `/api/http/routers` (und mit `TRAEFIK_TCP_ROUTERS=true`
auf `/api/tcp/routers`). Am einfachsten schaltest du die API auf Traefiks internem Port 8080
ein und gibst diesen Port **nicht** am Host frei:

```yaml
services:
  traefik:
    command:
      - --api=true
      - --api.insecure=true   # stellt die API am Entrypoint "traefik" auf Port 8080 bereit
    # 8080 nicht unter "ports:" freigeben
    networks:
      - proxy
```

`traefik-pihole-sync` hängt im selben Docker-Netz und nutzt
`TRAEFIK_API_URL=http://traefik:8080`. Stellst du das Dashboard schon über einen Router
bereit, kannst du `TRAEFIK_API_URL` auch darauf zeigen lassen, solange die URL ohne
interaktive Anmeldung erreichbar ist.

## Konfiguration

| Variable | Standard | Beschreibung |
|---|---|---|
| `TRAEFIK_API_URL` | `http://traefik:8080` | Basis-URL der Traefik-API |
| `TRAEFIK_TCP_ROUTERS` | `false` | Auch TCP-Router lesen (`HostSNI()`-Regeln) |
| `PIHOLE_URL` | – (Pflicht) | Basis-URL von Pi-hole; mehrere Instanzen durch Komma getrennt |
| `PIHOLE_PASSWORD_FILE` | – | Datei mit dem App-Passwort; eine Kommaliste ordnet jeder Instanz eine Datei zu |
| `PIHOLE_PASSWORD` | – | App-Passwort; ein Wert für alle oder eine Kommaliste mit einem Wert pro Instanz |
| `PIHOLE_VERIFY_TLS` | `true` | `true`, `false` oder der Pfad zu einer CA-Datei für Pi-hole über HTTPS |
| `RECORD_TYPE` | `A` | `A` oder `CNAME` |
| `TARGET_IP` | – | IPv4-Adresse für A-Einträge. Im A-Modus Pflicht, wenn `TARGET_IPV6` fehlt |
| `TARGET_IPV6` | – | IPv6-Adresse; legt zusätzlich AAAA-Einträge an |
| `CNAME_TARGET` | – | CNAME-Ziel (Pflicht bei `RECORD_TYPE=CNAME`) |
| `DOMAINS` | – (alle) | Domains, durch Komma getrennt; nur Hostnamen darin werden übernommen |
| `INCLUDE_APEX` | `false` | Zusätzlich einen Eintrag für jede Domain aus `DOMAINS`, die mindestens einen Hostnamen hat |
| `SYNC_INTERVAL` | `60` | Sekunden zwischen zwei Durchläufen |
| `DELETE_THRESHOLD` | `3` | So viele Durchläufe muss ein Host fehlen, bevor sein Eintrag gelöscht wird |
| `DRY_RUN` | `false` | Änderungen nur protokollieren, nicht schreiben |
| `STATE_FILE` | `/data/state.json` | Hier steht, welche Einträge das Tool angelegt hat |
| `HEALTH_FILE` | `/tmp/traefik-pihole-sync.health` | Wird nach jedem erfolgreichen Durchlauf aktualisiert |
| `HEALTH_MAX_AGE` | `max(300, 3 × SYNC_INTERVAL)` | Ab diesem Alter in Sekunden schlägt der Healthcheck fehl |
| `HEARTBEAT` | `3600` | Sekunden zwischen zwei Statuszeilen im Log; `0` schaltet sie ab |
| `WRITE_DELAY` | `0.5` | Wartezeit in Sekunden nach jedem Schreibvorgang (jeder startet den DNS-Dienst von Pi-hole neu) |
| `MAX_RETRIES` | `5` | Versuche pro Pi-hole-Anfrage bei Verbindungsfehlern oder Rate-Limit |
| `REQUEST_TIMEOUT` | `10` | HTTP-Timeout in Sekunden |
| `LOG_LEVEL` | `INFO` | `DEBUG` zeigt jeden Router und jeden Vergleich |

Passwörter mit Komma: nutze `PIHOLE_PASSWORD_FILE` oder `PIHOLE_PASSWORD` mit nur einem
Pi-hole.

### CNAME-Modus

```yaml
RECORD_TYPE: CNAME
CNAME_TARGET: proxy.example.com
TARGET_IP: 192.0.2.10   # optional: legt auch proxy.example.com → 192.0.2.10 an
```

Jeder Hostname wird zu `<host> CNAME proxy.example.com`. Ändert sich die IP deines Proxys,
muss nur ein Eintrag angepasst werden. Pi-hole kann den CNAME nur auflösen, wenn es das Ziel
kennt. Setze also `TARGET_IP`/`TARGET_IPV6` oder lege den Eintrag für das Ziel selbst an.

### Mehrere Pi-holes

```yaml
PIHOLE_URL: https://pihole1.example.com,https://pihole2.example.com
PIHOLE_PASSWORD_FILE: /run/secrets/pihole1,/run/secrets/pihole2
```

Jede Instanz wird für sich verglichen und aktualisiert und hat ihren eigenen Teil in der
State-Datei. Ist eine Instanz nicht erreichbar, werden die anderen trotzdem aktualisiert.
Gleichst du lokale DNS-Einträge schon mit einem anderen Tool zwischen deinen Pi-holes ab,
trag hier nur das primäre ein.

## Logs und Healthcheck

Routinearbeit landet auf `DEBUG`. Auf `INFO` siehst du Änderungen, Warnungen und eine
Statuszeile pro Stunde. Fällt eine Quelle dauerhaft aus (Traefik oder ein Pi-hole), wird
das einmal gemeldet und ihre Rückkehr ebenfalls einmal.

Das Image hat einen `HEALTHCHECK`. Er ruft `python -m traefik_pihole_sync --healthcheck` auf
und meldet „unhealthy“, wenn der letzte vollständig erfolgreiche Durchlauf älter als
`HEALTH_MAX_AGE` ist.

```bash
docker run --rm ghcr.io/schnuecks/traefik-pihole-sync:latest --version
docker compose run --rm traefik-pihole-sync --once   # ein Durchlauf, dann Ende
```

## Umstieg von früheren Versionen

Frühere Versionen (ein einzelnes Skript) speicherten eine Liste von Hostnamen in
`/data/managed_hosts.json`. Beim ersten Start mit einer neuen `/data/state.json` wird diese
Datei automatisch übernommen. Ihre Hostnamen werden zu A-Einträgen mit `TARGET_IP` für das
**erste** Pi-hole in `PIHOLE_URL`. Die alte Datei bleibt liegen. Die alten Variablen
`ALLOWED_ZONE`, `PIHOLE_APP_PASSWORD` und `PIHOLE_APP_PASSWORD_FILE` funktionieren weiter.

Darauf solltest du achten:

- `INCLUDE_APEX` ist jetzt standardmäßig `false`. Setze es auf `true`, wenn du es brauchst.
- Der Container läuft nicht mehr als root. Passe den Besitzer des Datenverzeichnisses an
  (siehe oben).
- TLS-Zertifikate werden geprüft. Bei einem selbstsignierten Zertifikat von Pi-hole setze
  `PIHOLE_VERIFY_TLS` auf deine CA-Datei oder auf `false`.

## Entwicklung

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && pytest
```

## Unterstützen

traefik-pihole-sync ist kostenlos und bleibt es. Wenn es dir Zeit spart, kannst du mir einen
Kaffee ausgeben; das hält das Projekt am Laufen. Danke!

<p>
  <a href="https://buymeacoffee.com/il6hhwtzr6"><img src="https://img.shields.io/badge/Buy_me_a_coffee-10_%E2%82%AC-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy me a coffee: 10 €"></a>
  <a href="https://buymeacoffee.com/il6hhwtzr6"><img src="https://img.shields.io/badge/Buy_me_a_coffee-25_%E2%82%AC-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy me a coffee: 25 €"></a>
  <a href="https://buymeacoffee.com/il6hhwtzr6"><img src="https://img.shields.io/badge/Buy_me_a_coffee-50_%E2%82%AC-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy me a coffee: 50 €"></a>
</p>

## Rückmeldungen

Fehler und Ideen sind als
[Issue auf GitHub](https://github.com/Schnuecks/traefik-pihole-sync/issues) willkommen. Bei
Fehlern hänge bitte das Log mit `LOG_LEVEL=DEBUG` an; Hostnamen und Adressen, die du nicht
teilen möchtest, kannst du vorher ersetzen. Siehe auch [CONTRIBUTING](CONTRIBUTING.md) und
[SECURITY](SECURITY.md).

Was sich in einer Version geändert hat, steht im [CHANGELOG](CHANGELOG.md) (auf Englisch).

## Lizenz

Copyright (c) 2026 Schnuecks. Veröffentlicht unter der [MIT-Lizenz](LICENSE).

Dieses Projekt steht in keiner Verbindung zu Traefik Labs oder Pi-hole LLC und wird von
ihnen nicht unterstützt. Traefik und Pi-hole sind Marken ihrer jeweiligen Inhaber.
