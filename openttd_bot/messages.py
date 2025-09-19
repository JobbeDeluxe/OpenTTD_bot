"""Message catalogue support for the OpenTTD helper bot."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


LOGGER = logging.getLogger(__name__)


_SECTION_HEADER_RE = re.compile(r"^-+\[(?P<section>[^\]]+)\]-+$")


DEFAULT_MESSAGES: dict[str, Any] = {
    'welcome': ['---------------------[ENG]---------------------',
        'Welcome {client_name}!',
        'This server is maintained by {bot_name}.',
        '---------------------[DE]---------------------',
        'Willkommen {client_name}!',
        'Dieser Server wird von {bot_name} betreut.'],
    'help': ['---------------------[ENG]---------------------',
        'Available commands: !help, !rules, !pw <password>, !reset, !confirm.',
        'Open the player selection via the Online Players button (icon with the person in a top hat), '
        'select {bot_name} and use the whisper function to send !pw <password> privately.',
        '---------------------[DE]---------------------',
        'Verfügbare Befehle: !help, !rules, !pw <passwort>, !reset, !confirm.',
        'Öffne die Spielerliste über den "Online-Spieler"-Button (Symbol mit dem Mann im Zylinder), wähle '
        '{bot_name} und nutze die Flüstern-Funktion, um !pw <passwort> privat zu senden.'],
    'rules': ['---------------------[ENG]---------------------',
        '1. Respect other players.',
        '2. Do not block tracks.',
        '---------------------[DE]---------------------',
        '1. Respektiere andere Spieler.',
        '2. Blockiere keine Strecken.'],
    'password_instructions': ['---------------------[ENG]---------------------',
        'Whisper {bot_name} via the player selection opened through the Online Players button (icon with '
        'the person in a top hat) using !pw <password> to protect your company.',
        'The bot will automatically restore the saved password after server restarts.',
        '---------------------[DE]---------------------',
        'Flüstere {bot_name} über die Spielerliste, die du über den "Online-Spieler"-Button (Symbol mit '
        'dem Mann im Zylinder) öffnest, mit !pw <passwort>, um deine Firma zu schützen.',
        'Nach Serverneustarts setzt der Bot das gespeicherte Passwort automatisch wieder.'],
    'password_whisper_only': ['---------------------[ENG]---------------------',
        'Please use the player selection, pick {bot_name} and send !pw <password> there instead of public '
        'chat.',
        '---------------------[DE]---------------------',
        'Bitte nutze die Spielerauswahl, wähle {bot_name} und sende dort !pw <passwort>, nicht im '
        'öffentlichen Chat.'],
    'password_missing_argument': ['---------------------[ENG]---------------------',
        'Please provide a password: !pw <password> or !pw clear.',
        '---------------------[DE]---------------------',
        'Bitte gib ein Passwort an: !pw <passwort> oder !pw clear.'],
    'password_invalid': ['---------------------[ENG]---------------------',
        'Invalid password.',
        '---------------------[DE]---------------------',
        'Ungültiges Passwort.'],
    'password_set_success': ['---------------------[ENG]---------------------',
        'Password for company {company_name} has been saved.',
        '---------------------[DE]---------------------',
        'Passwort für Firma {company_name} wurde gespeichert.'],
    'password_clear_success': ['---------------------[ENG]---------------------',
        'Password for company {company_name} has been removed.',
        '---------------------[DE]---------------------',
        'Passwort für Firma {company_name} wurde entfernt.'],
    'password_not_in_company': ['---------------------[ENG]---------------------',
        'You need to be part of a company to set a password.',
        '---------------------[DE]---------------------',
        'Du musst einer Firma angehören, um ein Passwort zu setzen.'],
    'reset_not_in_company': ['---------------------[ENG]---------------------',
        'You are currently not in a company.',
        '---------------------[DE]---------------------',
        'Du befindest dich aktuell in keiner Firma.'],
    'reset_prompt': ['---------------------[ENG]---------------------',
        'You want to reset company {company_name}.',
        'Leave the company first (e.g. become a spectator) and then send !confirm.',
        '---------------------[DE]---------------------',
        'Du möchtest Firma {company_name} zurücksetzen.',
        'Verlasse zuerst die Firma (z. B. Zuschauer) und sende dann !confirm.'],
    'reset_confirmed': ['---------------------[ENG]---------------------',
        'Company {company_name} has been reset.',
        '---------------------[DE]---------------------',
        'Firma {company_name} wurde zurückgesetzt.'],
    'reset_no_pending': ['---------------------[ENG]---------------------',
        'There is no pending reset.',
        '---------------------[DE]---------------------',
        'Es liegt keine offene Zurücksetzung vor.'],
    'reset_wrong_company': ['---------------------[ENG]---------------------',
        'Your reset request was for company {company_name}. Please use !reset again in the company you '
        'want to reset.',
        '---------------------[DE]---------------------',
        'Deine Reset-Anfrage bezog sich auf Firma {company_name}. Bitte sende !reset erneut in der '
        'gewünschten Firma.'],
    'reset_still_in_company': ['---------------------[ENG]---------------------',
        'You are still in company {company_name}. Leave it first and then send !confirm.',
        '---------------------[DE]---------------------',
        'Du befindest dich noch in Firma {company_name}. Verlasse sie zuerst und sende dann !confirm.'],
    'company_password_reapplied': ['---------------------[ENG]---------------------',
        'The stored password for company {company_name} has been applied again.',
        '---------------------[DE]---------------------',
        'Das gespeicherte Passwort für Firma {company_name} wurde erneut gesetzt.'],
    'newgame_missing_password': ['---------------------[ENG]---------------------',
        'Please provide the admin password: !newgame <password>.',
        '---------------------[DE]---------------------',
        'Bitte gib das Admin-Passwort an: !newgame <passwort>.'],
    'newgame_invalid_password': ['---------------------[ENG]---------------------',
        'Invalid admin password.',
        '---------------------[DE]---------------------',
        'Ungültiges Admin-Passwort.'],
    'newgame_started': ['---------------------[ENG]---------------------',
        'Clearing all company passwords and starting a new game.',
        '---------------------[DE]---------------------',
        'Alle Firmenpasswörter werden gelöscht und ein neues Spiel wird gestartet.'],
}

@dataclass(slots=True)
class MessageCatalog:
    """Wrapper around the user configurable message catalogue."""

    data: Mapping[str, Any]

    @classmethod
    def load(cls, path: Path) -> "MessageCatalog":
        """Load a message file from disk, falling back to defaults."""

        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Failed to load messages.json, using defaults: %%s", exc)
                loaded = {}
        else:
            loaded = {}

        data = dict(DEFAULT_MESSAGES)
        for key, value in loaded.items():
            data[key] = value
        return cls(data)

    def get_lines(self, key: str, **context: Any) -> list[str]:
        """Return a list of formatted message lines for *key*."""

        raw = self.data.get(key)
        if raw is None:
            return []
        if isinstance(raw, str):
            raw_lines: Iterable[str] = [raw]
        else:
            raw_lines = raw
        return [line.format(**context) for line in raw_lines]

    def get_message(self, key: str, default: str = "", joiner: str = " ", **context: Any) -> str:
        """Return a single formatted message for *key*."""

        raw = self.data.get(key)
        if raw is None:
            return default
        if isinstance(raw, str):
            return raw.format(**context)
        return joiner.join(str(part) for part in raw).format(**context)

    def has(self, key: str) -> bool:
        """Return whether a message is configured for *key*."""

        return key in self.data

    def merge_sections(self, lines: Iterable[str], joiner: str = "\n") -> list[str]:
        """Merge lines that are grouped by language markers into larger blocks."""

        sections: "OrderedDict[str, list[str]]" = OrderedDict()
        headers: dict[str, str | None] = {}
        order: list[str] = []
        current_section: str | None = None

        def ensure_section(key: str) -> list[str]:
            if key not in sections:
                sections[key] = []
                headers.setdefault(key, None)
                order.append(key)
            return sections[key]

        for line in lines:
            stripped = line.strip()
            header = _SECTION_HEADER_RE.match(stripped)
            if header:
                section = header.group("section")
                block = ensure_section(section)
                if headers[section] is None:
                    headers[section] = line
                elif block and block[-1].strip():
                    block.append("")
                current_section = section
                continue

            key = current_section if current_section is not None else ""
            block = ensure_section(key)
            block.append(line)

        merged: list[str] = []
        for key in order:
            block = _trim_empty_edges(sections[key])
            header = headers.get(key)
            if header is None and not block:
                continue
            parts: list[str] = []
            if header:
                parts.append(header)
            parts.extend(block)
            merged.append(joiner.join(parts))

        return merged


def _trim_empty_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)

    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1

    return lines[start:end]
