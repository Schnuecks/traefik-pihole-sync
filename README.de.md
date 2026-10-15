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
2. behält nur Hostnamen innerhalb von `DOMAINS` (Pflicht, siehe [Warum DOMAINS Pflicht ist](#warum-domains-pflicht-ist)),
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

### Warum DOMAINS Pflicht ist

Lokale DNS-Einträge in Pi-hole haben für jedes Gerät in deinem Netz Vorrang vor dem
öffentlichen DNS. Ohne Filter würde ein Router mit ``Host(`login.example.org`)`` (eine
fremde Domain oder einfach ein Tippfehler) diesen Namen im ganzen Netz auf deinen Proxy
umbiegen. Deshalb übernimmt das Tool nur Hostnamen innerhalb der Domains, die du in
`DOMAINS` angibst. Willst du wirklich jeden Hostnamen aus Traefik, setze `DOMAINS=*`; das
Tool warnt dann bei jedem Start.

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
   Konfiguration zwar lesen, aber nicht ändern. Mit ihr kann das App-Passwort **jede**
   Einstellung von Pi-hole ändern. Behandle es also wie ein Admin-Passwort: nur in einer
   Docker-Secret-Datei ablegen, nie in `compose.yml` oder `.env`.
3. Öffne **Settings → Web interface / API**, klicke auf **Configure app password**,
   kopiere das erzeugte Passwort und übernimm es.
4. Schreibe das Passwort in die Secret-Datei (oben `./secrets/pihole_password.txt`). Sie
   darf nur das Passwort enthalten.

Das Passwort geht bei der Anmeldung an Pi-hole über das Netz, die Sitzungs-ID bei jeder
Anfrage. Über `http://` geht beides unverschlüsselt. Das ist nur in Ordnung, wenn das Tool
Pi-hole im selben Docker-Netz oder auf demselben Host erreicht. Sonst nutze eine
`https://`-URL. Bei einem Zertifikat deiner eigenen CA setze `PIHOLE_VERIFY_TLS` auf den
Pfad der CA-Datei (in den Container eingebunden) statt auf `false`. Weiterleitungen folgt
das Tool nie; gib in `PIHOLE_URL` also die endgültige Adresse an.

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

Bedenke: Die API zeigt Traefiks komplette Konfiguration samt Middlewares und
Backend-Adressen jedem Container, der Port 8080 erreicht. Mit `--api.insecure=true` ist das
jeder Container im Netz `proxy`. Um das einzuschränken, stelle die API über einen eigenen
Entrypoint bereit und erlaube nur ein kleines Netz, das sich nur Traefik und dieses Tool
teilen:

```yaml
services:
  traefik:
    command:
      - --api=true                                # ohne --api.insecure
      - --entrypoints.traefikapi.address=:8080
    labels:
      - traefik.enable=true
      - traefik.http.routers.api.entrypoints=traefikapi
      - traefik.http.routers.api.rule=PathPrefix(`/api`)
      - traefik.http.routers.api.service=api@internal
      - traefik.http.routers.api.middlewares=api-allow
      - traefik.http.middlewares.api-allow.ipallowlist.sourcerange=172.31.250.0/29
    networks:
      - proxy
      - traefik-api

  traefik-pihole-sync:
    networks:
      - traefik-api

networks:
  traefik-api:
    ipam:
      config:
        - subnet: 172.31.250.0/29
```

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
| `DOMAINS` | – (Pflicht) | Domains, durch Komma getrennt; nur Hostnamen darin werden übernommen. `*` übernimmt jeden Hostnamen (nicht empfohlen, siehe oben) |
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

- **2.0.0:** `DOMAINS` (oder das alte `ALLOWED_ZONE`) ist Pflicht. Ohne startet das Tool
  mit einer Fehlermeldung nicht. Setze es auf deine eigenen Domains oder auf `*`, um das
  alte Verhalten „alle Hostnamen“ zu behalten.
- `INCLUDE_APEX` ist jetzt standardmäßig `false`. Setze es auf `true`, wenn du es brauchst.
- Der Container läuft nicht mehr als root. Passe den Besitzer des Datenverzeichnisses an
  (siehe oben).
- TLS-Zertifikate werden geprüft. Bei einem selbstsignierten Zertifikat von Pi-hole setze
  `PIHOLE_VERIFY_TLS` auf deine CA-Datei (oder, nicht empfohlen, auf `false`).

## Entwicklung

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && ruff format --check . && pytest
```

## Sicherheit

Lokale DNS-Einträge haben im ganzen Netz Vorrang vor dem öffentlichen DNS, deshalb ist das Tool
streng bei dem, was es schreibt:

- **Nur deine Domains:** `DOMAINS` ist Pflicht; Hostnamen außerhalb davon werden nie eingetragen.
- **Nur eigene Einträge:** Einträge, die es nicht selbst angelegt hat, ändert oder löscht es nie,
  gelöscht wird erst nach mehreren Durchläufen, und ein Probelauf zeigt vorher jede Änderung.
- **Zugangsdaten:** Pi-hole-Passwort aus einem Docker-Secret, wird nie über eine Weiterleitung
  mitgeschickt.
- **Bei jeder Änderung geprüft:** Tests, Trivy-Scan des Images, Dependabot; GitHub Actions auf
  Commit-Hashes und das Basis-Image auf einen Digest festgelegt.
- **Überprüft:** Ein KI-gestützter Sicherheits-Review hat zu Version 2.0.0 geführt; die Parser
  und die Regel „fremde Einträge nie anfassen“ wurden zusätzlich mit Zufallseingaben gefuzzt.

Sicherheitslücken bitte vertraulich melden, siehe [SECURITY.md](SECURITY.md).

## Wie es entsteht

traefik-pihole-sync entsteht mit Unterstützung eines KI-Assistenten. Funktionen und Verhalten
lege ich fest, prüfe die Änderungen und teste sie in meinem eigenen Homelab mit Traefik und Pi-
hole. Veröffentlicht wird nur, was die automatischen Prüfungen besteht: die Tests und ein
Sicherheitsscan des Container-Images.

## Unterstützen

traefik-pihole-sync ist kostenlos und bleibt es. Wenn es dir Zeit spart, kannst du mir einen
Kaffee auf Ko-fi ausgeben; das hält das Projekt am Laufen. Danke!

<p>
  <a href="https://ko-fi.com/schnuecks"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support me on Ko-fi"></a>
</p>

## Rückmeldungen

Fehler und Ideen sind als
[Issue auf GitHub](https://github.com/Schnuecks/traefik-pihole-sync/issues) willkommen. Bei
Fehlern hänge bitte das Log mit `LOG_LEVEL=DEBUG` an; Hostnamen und Adressen, die du nicht
teilen möchtest, kannst du vorher ersetzen. Siehe auch [CONTRIBUTING](CONTRIBUTING.md) und
[SECURITY](SECURITY.md).

Was sich in einer Version geändert hat, steht im [CHANGELOG](CHANGELOG.md) (auf Englisch).

**Was du erwarten kannst:** traefik-pihole-sync ist ein Hobby-Projekt, das ich in meinem
eigenen Homelab nutze. Issues und Pull Requests schaue ich mir an, wenn ich Zeit habe, ohne
feste Antwortzeit. Das Tool macht bewusst nur eine Sache: die lokalen DNS-Einträge von
Pi-hole sicher mit Traefik abgleichen. Ideen, die das besser machen, sind sehr willkommen;
Funktionen, die daraus etwas viel Größeres machen würden, lehne ich eventuell ab, damit es
klein und vertrauenswürdig bleibt.

## Lizenz

Copyright (c) 2026 Schnuecks. Veröffentlicht unter der [MIT-Lizenz](LICENSE).

Dieses Projekt steht in keiner Verbindung zu Traefik Labs oder Pi-hole LLC und wird von
ihnen nicht unterstützt. Traefik und Pi-hole sind Marken ihrer jeweiligen Inhaber.
