"""Message catalogue support for the OpenTTD helper bot."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Mapping


LOGGER = logging.getLogger(__name__)


DEFAULT_MESSAGES: dict[str, Any] = {
    "welcome": [
        "Willkommen {client_name}!",
        "Dieser Server wird von {bot_name} betreut.",
    ],
    "help": [
        "Verfügbare Befehle: !help, !rules, !pw <passwort>, !reset, !confirm.",
        "Sende Befehle an den Server mit /server <text>.",
    ],
    "rules": [
        "1. Respektiere andere Spieler.",
        "2. Blockiere keine Strecken.",
    ],
    "password_instructions": [
        "Sichere deine Firma mit /server !pw <passwort>.",
        "Das Passwort wird automatisch nach Serverneustarts wieder gesetzt.",
    ],
    "password_whisper_only": "Bitte sende !pw per /server, damit dein Passwort geheim bleibt.",
    "password_missing_argument": "Bitte gib ein Passwort an: !pw <passwort> oder !pw clear.",
    "password_invalid": "Ungültiges Passwort.",
    "password_set_success": "Passwort für Firma {company_name} wurde gespeichert.",
    "password_clear_success": "Passwort für Firma {company_name} wurde entfernt.",
    "password_not_in_company": "Du musst einer Firma angehören um ein Passwort zu setzen.",
    "reset_not_in_company": "Du befindest dich aktuell in keiner Firma.",
    "reset_prompt": [
        "Du möchtest Firma {company_name} zurücksetzen.",
        "Sende !confirm um dies zu bestätigen.",
    ],
    "reset_confirmed": "Firma {company_name} wurde zurückgesetzt.",
    "reset_no_pending": "Es liegt keine offene Zurücksetzung vor.",
    "reset_wrong_company": "Du befindest dich nicht mehr in Firma {company_name}. Reset abgebrochen.",
    "company_password_reapplied": "Das gespeicherte Passwort für Firma {company_name} wurde erneut gesetzt.",
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
