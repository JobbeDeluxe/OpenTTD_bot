"""Persistent state handling for the OpenTTD helper bot."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from threading import Lock
from typing import Dict, Iterator

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PersistentState:
    """Container for the on-disk state."""

    companies: Dict[str, str] = field(default_factory=dict)


class StateStore:
    """Manage persisted state on disk."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self._state = PersistentState()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Could not read state file %s: %s", self.path, exc)
            return
        companies = data.get("companies", {})
        if isinstance(companies, dict):
            self._state.companies = {
                str(company_id): str(password)
                for company_id, password in companies.items()
                if password is not None
            }

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump({"companies": self._state.companies}, handle, indent=2, ensure_ascii=False)
        tmp_path.replace(self.path)

    def get_company_password(self, company_id: int) -> str | None:
        """Return the stored password for *company_id* if present."""

        with self._lock:
            return self._state.companies.get(str(company_id))

    def set_company_password(self, company_id: int, password: str) -> None:
        """Persist the password for *company_id*."""

        with self._lock:
            self._state.companies[str(company_id)] = password
            self._write()

    def clear_company_password(self, company_id: int) -> None:
        """Remove any stored password for *company_id*."""

        with self._lock:
            if str(company_id) in self._state.companies:
                del self._state.companies[str(company_id)]
                self._write()

    def clear_all_company_passwords(self) -> None:
        """Remove all stored company passwords."""

        with self._lock:
            if not self._state.companies:
                return
            self._state.companies.clear()
            self._write()

    def iter_company_passwords(self) -> Iterator[tuple[int, str]]:
        """Yield all stored company passwords."""

        with self._lock:
            for company_id, password in self._state.companies.items():
                yield int(company_id), password
