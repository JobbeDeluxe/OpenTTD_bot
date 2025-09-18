# OpenTTD Server Helper Bot

Ein Python-Bot, der über den Admin-Port eines OpenTTD-Servers läuft und dabei hilft, Serverregeln zu verteilen, Firmenpasswörter sicher zu verwalten und administrative Aufgaben (z. B. Firmen zurücksetzen) über Chatbefehle zu automatisieren.

## Features

- Reagiert auf Befehle `!help`, `!rules`, `!pw`, `!reset` und `!confirm` sowohl im öffentlichen Chat als auch per Flüstern.
- Erzwingt, dass Passwörter ausschließlich per `/whisper <BotName> !pw <passwort>` privat übermittelt werden.
- Speichert Firmenpasswörter persistent und setzt sie nach einem Serverneustart automatisch wieder.
- Schickt neuen Spielern automatisch eine Begrüßung sowie Hilfe- und Regelhinweise.
- Informiert neue Firmeninhaber direkt darüber, wie ein Passwort gesetzt wird.
- Stellt sicher, dass `!reset` nur die Firma des aufrufenden Spielers betrifft und mit `!confirm` abgesichert wird.

## Installation

1. Abhängigkeiten installieren (Python ≥ 3.11 wird empfohlen):

   ```bash
   python -m pip install -r <(printf 'pyOpenTTDAdmin>=1.0.2\n')
   ```

2. Stelle sicher, dass sich das Verzeichnis `openttd_bot` aus diesem Repository im selben Ordner wie `bot.py` befindet. Wenn du
   den Bot in einem Container betreibst, musst du daher das komplette Projektverzeichnis mounten.

3. Umgebungsvariablen setzen (siehe Tabelle unten) und anschließend den Bot starten:

   ```bash
   export OTTD_HOST=openttd2
   export OTTD_ADMIN_PORT=3977
   export OTTD_ADMIN_PASSWORD=meinadminpasswort
   export BOT_NAME=ServerBot
   export COMMAND_PREFIX=!
   export STATE_FILE=/data/state.json
   export MESSAGES_FILE=/config/messages.json
   python bot.py
   ```

### Konfiguration per Umgebung

| Variable | Beschreibung | Standard |
| --- | --- | --- |
| `OTTD_HOST` | Hostname oder IP des OpenTTD-Servers | `127.0.0.1` |
| `OTTD_ADMIN_PORT` | Admin-Port des Servers | `3977` |
| `OTTD_ADMIN_PASSWORD` | Admin-Passwort des Servers (Pflicht) | – |
| `BOT_NAME` | Name des Bots (erscheint im Chat) | `ServerBot` |
| `COMMAND_PREFIX` | Präfix für Chatbefehle | `!` |
| `STATE_FILE` | Speicherort für die persistenten Passwörter | `./state.json` |
| `MESSAGES_FILE` | Pfad zur JSON-Datei mit Nachrichtentexten | `./messages.json` |
| `STARTUP_REAPPLY_DELAY_SECONDS` | Verzögerung, bevor gespeicherte Passwörter nach dem Start neu gesetzt werden | `5` |
| `RECONNECT_DELAY_SECONDS` | Wartezeit nach einem Fehler, bevor ein Reconnect versucht wird | `5` |

Die Datei `messages.json` kann nach eigenen Wünschen angepasst werden (Texte, Sprache, zusätzliche Hinweise). Platzhalter wie `{client_name}`, `{bot_name}` oder `{company_name}` werden automatisch ersetzt.

## OpenTTD-Serverkonfiguration

Damit der Bot sich verbinden kann, muss in der OpenTTD-Konfigurationsdatei `openttd.cfg` der Admin-Zugang korrekt
eingestellt sein. Die Datei befindet sich je nach Installation beispielsweise unter `/config/openttd.cfg` (Docker-Volume)
oder im Benutzerverzeichnis (`~/.openttd/openttd.cfg`). Relevante Optionen innerhalb des Blocks `[admin]`:

```ini
[admin]
admin_port = 3977
admin_password = topsecret
admin_bind = 0.0.0.0
admin_chat = true
```

- `admin_port` muss mit der Umgebungsvariable `OTTD_ADMIN_PORT` übereinstimmen.
- `admin_password` legt das Passwort für den Admin-Port fest und muss dem Wert von `OTTD_ADMIN_PASSWORD` entsprechen.
- `admin_bind` bestimmt die IP-Adresse, an die der Admin-Port gebunden wird. Für Container-Setups empfiehlt sich `0.0.0.0`.
- `admin_chat` sollte auf `true` stehen, damit der Bot Chatnachrichten empfangen kann.

Nach Änderungen an der Konfiguration den Server neu starten oder mit `rcon reload_config` die Einstellungen neu laden.

## Docker-/Portainer-Integration

Der Bot wurde so aufgebaut, dass er im gleichen Docker-Netzwerk wie der OpenTTD-Server laufen kann. Wichtig ist, dass das
gesamte Projektverzeichnis (inklusive des Ordners `openttd_bot`) im Container unter `/app` zur Verfügung steht. Ein
Beispiel-Stack für Portainer könnte wie folgt aussehen:

```yaml
version: "3.8"

services:
  openttd2:
    image: ghcr.io/ropenttd/openttd:latest
    container_name: openttd2
    restart: unless-stopped
    environment:
      - TZ=Europe/Berlin
      - loadgame=last-autosave
    ports:
      - "3979:3979/tcp"
      - "3979:3979/udp"
    volumes:
      - /srv/docker/openttd2/server:/config
    networks: [games]

  ottd-bot2:
    image: python:3.11-slim
    container_name: ottd-bot2
    restart: unless-stopped
    environment:
      - TZ=Europe/Berlin
      - PYTHONUNBUFFERED=1
      - OTTD_HOST=openttd2
      - OTTD_ADMIN_PORT=3977
      - OTTD_ADMIN_PASSWORD=topsecret
      - BOT_NAME=ServerBot
      - COMMAND_PREFIX=!
      - STATE_FILE=/data/state.json
      - MESSAGES_FILE=/config/messages.json
      - STARTUP_REAPPLY_DELAY_SECONDS=5
    volumes:
      - /srv/docker/openttd/bot2/data:/data
      - /srv/docker/openttd/bot2/messages.json:/config/messages.json:ro
      - /srv/docker/openttd/bot2:/app:ro
    working_dir: /app
    command: >
      sh -c "
        set -e;
        apt-get update &&
        apt-get install -y --no-install-recommends netcat-openbsd iputils-ping &&
        rm -rf /var/lib/apt/lists/*;
        if [ -f /app/requirements.txt ]; then
          pip install --no-cache-dir -r /app/requirements.txt;
        else
          pip install --no-cache-dir pyOpenTTDAdmin typing_extensions;
        fi;
        echo '== Connectivity check ==';
        nc -vz -w2 ${OTTD_HOST:-openttd2} ${OTTD_ADMIN_PORT:-3977} || echo 'WARN: Admin-Port nicht erreichbar';
        ping -c 2 ${OTTD_HOST:-openttd2} || true;
        echo '== Starting bot ==';
        exec python /app/bot.py
      "
    depends_on:
      - openttd2
    networks: [games]

networks:
  games:
    driver: bridge
```

Die Datei `messages.json` aus diesem Repository kann als Vorlage verwendet und an die eigenen Bedürfnisse angepasst werden. Da
das gesamte Verzeichnis `/srv/docker/openttd/bot2` eingebunden wird, stehen `bot.py`, `messages.json` und der Ordner
`openttd_bot` automatisch im Container zur Verfügung. Passwörter werden im Volume `/srv/docker/openttd/bot2/data` gespeichert,
sodass sie Container-Neustarts überstehen.


## Tests

Zum Ausführen der Tests:

```bash
python -m pip install pytest
python -m pytest
```

## Lizenz

Veröffentlicht unter der MIT-Lizenz (siehe `LICENSE`).

---

## English Instructions

### Features

- Responds to `!help`, `!rules`, `!pw`, `!reset` and `!confirm` in public chat and via whispers.
- Enforces password submission via private message (`/whisper <BotName> !pw <password>`).
- Persists company passwords and reapplies them after the server restarts.
- Welcomes new players automatically and shares help/rules messages.
- Informs new company owners how to set a password.
- Protects `!reset` with a confirmation step and limits it to the caller's company.

### Installation

1. Install dependencies (Python ≥ 3.11 recommended):

   ```bash
   python -m pip install -r <(printf 'pyOpenTTDAdmin>=1.0.2\n')
   ```

2. Place the `openttd_bot` directory from this repository next to `bot.py`. When running inside a container you need to mount
   the entire project directory so both `bot.py` and the package folder are available.

3. Set the required environment variables (see table below) and start the bot:

   ```bash
   export OTTD_HOST=openttd2
   export OTTD_ADMIN_PORT=3977
   export OTTD_ADMIN_PASSWORD=myadminpassword
   export BOT_NAME=ServerBot
   export COMMAND_PREFIX=!
   export STATE_FILE=/data/state.json
   export MESSAGES_FILE=/config/messages.json
   python bot.py
   ```

### Environment variables

| Variable | Description | Default |
| --- | --- | --- |
| `OTTD_HOST` | Hostname or IP address of the OpenTTD server | `127.0.0.1` |
| `OTTD_ADMIN_PORT` | Admin port of the server | `3977` |
| `OTTD_ADMIN_PASSWORD` | Admin password of the server (required) | – |
| `BOT_NAME` | Display name of the bot | `ServerBot` |
| `COMMAND_PREFIX` | Prefix used for chat commands | `!` |
| `STATE_FILE` | Location where persistent passwords are stored | `./state.json` |
| `MESSAGES_FILE` | Path to the JSON file with message templates | `./messages.json` |
| `STARTUP_REAPPLY_DELAY_SECONDS` | Delay before reapplied passwords are sent after startup | `5` |
| `RECONNECT_DELAY_SECONDS` | Wait time before reconnect attempts after an error | `5` |

You can adapt `messages.json` to your needs. Placeholders such as `{client_name}`, `{bot_name}` or `{company_name}` are
replaced automatically.

### OpenTTD server configuration

The admin interface must be configured in `openttd.cfg` so the bot can connect. Depending on your setup the file can be found
inside the Docker volume (for example `/config/openttd.cfg`) or in the user directory (`~/.openttd/openttd.cfg`). Relevant
options in the `[admin]` block:

```ini
[admin]
admin_port = 3977
admin_password = topsecret
admin_bind = 0.0.0.0
admin_chat = true
```

- `admin_port` must match the `OTTD_ADMIN_PORT` environment variable.
- `admin_password` sets the admin password and must match `OTTD_ADMIN_PASSWORD`.
- `admin_bind` controls which interface the admin port listens on; `0.0.0.0` works well for containers.
- `admin_chat` should be `true` so the bot receives chat messages.

Restart the server after changing the configuration or execute `rcon reload_config` to reload it live.

### Docker / Portainer example

The bot can run inside the same Docker network as the OpenTTD server. Mount the entire project directory (including
`openttd_bot`) to `/app` inside the container. A Portainer stack example:

```yaml
version: "3.8"

services:
  openttd2:
    image: ghcr.io/ropenttd/openttd:latest
    container_name: openttd2
    restart: unless-stopped
    environment:
      - TZ=Europe/Berlin
      - loadgame=last-autosave
    ports:
      - "3979:3979/tcp"
      - "3979:3979/udp"
    volumes:
      - /srv/docker/openttd2/server:/config
    networks: [games]

  ottd-bot2:
    image: python:3.11-slim
    container_name: ottd-bot2
    restart: unless-stopped
    environment:
      - TZ=Europe/Berlin
      - PYTHONUNBUFFERED=1
      - OTTD_HOST=openttd2
      - OTTD_ADMIN_PORT=3977
      - OTTD_ADMIN_PASSWORD=topsecret
      - BOT_NAME=ServerBot
      - COMMAND_PREFIX=!
      - STATE_FILE=/data/state.json
      - MESSAGES_FILE=/config/messages.json
      - STARTUP_REAPPLY_DELAY_SECONDS=5
    volumes:
      - /srv/docker/openttd/bot2/data:/data
      - /srv/docker/openttd/bot2/messages.json:/config/messages.json:ro
      - /srv/docker/openttd/bot2:/app:ro
    working_dir: /app
    command: >
      sh -c "
        set -e;
        apt-get update &&
        apt-get install -y --no-install-recommends netcat-openbsd iputils-ping &&
        rm -rf /var/lib/apt/lists/*;
        if [ -f /app/requirements.txt ]; then
          pip install --no-cache-dir -r /app/requirements.txt;
        else
          pip install --no-cache-dir pyOpenTTDAdmin typing_extensions;
        fi;
        echo '== Connectivity check ==';
        nc -vz -w2 ${OTTD_HOST:-openttd2} ${OTTD_ADMIN_PORT:-3977} || echo 'WARN: Admin port unreachable';
        ping -c 2 ${OTTD_HOST:-openttd2} || true;
        echo '== Starting bot ==';
        exec python /app/bot.py
      "
    depends_on:
      - openttd2
    networks: [games]

networks:
  games:
    driver: bridge
```

`messages.json` in this repository serves as a template you can adjust. Because the entire directory `/srv/docker/openttd/bot2`
is mounted, the container automatically sees `bot.py`, `messages.json`, and the `openttd_bot` package. Passwords are stored in
`/srv/docker/openttd/bot2/data`, so they survive container restarts.

### Tests

```bash
python -m pip install pytest
python -m pytest
```

### License

Released under the MIT License (see `LICENSE`).
