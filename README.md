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

| Variable                        | Beschreibung                                                                 | Standard          |
|---------------------------------|------------------------------------------------------------------------------|-------------------|
| `OTTD_HOST`                     | Hostname oder IP des OpenTTD-Servers                                         | `127.0.0.1`       |
| `OTTD_ADMIN_PORT`               | Admin-Port des Servers                                                       | `3977`            |
| `OTTD_ADMIN_PASSWORD`           | Admin-Passwort des Servers (Pflicht)                                         | –                 |
| `BOT_NAME`                      | Name des Bots (erscheint im Chat)                                            | `ServerBot`       |
| `COMMAND_PREFIX`                | Präfix für Chatbefehle                                                       | `!`               |
| `STATE_FILE`                    | Speicherort für die persistenten Passwörter                                  | `./state.json`    |
| `MESSAGES_FILE`                 | Pfad zur JSON-Datei mit Nachrichtentexten                                    | `./messages.json` |
| `STARTUP_REAPPLY_DELAY_SECONDS` | Verzögerung, bevor gespeicherte Passwörter nach dem Start neu gesetzt werden | `5`               |
| `RECONNECT_DELAY_SECONDS`       | Wartezeit nach einem Fehler, bevor ein Reconnect versucht wird               | `5`               |


Die Datei `messages.json` kann nach eigenen Wünschen angepasst werden (Texte, Sprache, zusätzliche Hinweise). Platzhalter wie `{client_name}`, `{bot_name}` oder `{company_name}` werden automatisch ersetzt.

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
