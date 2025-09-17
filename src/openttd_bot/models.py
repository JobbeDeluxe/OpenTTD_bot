"""Dataclasses used by the OpenTTD helper bot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SPECTATOR_COMPANY_ID = 255


@dataclass(slots=True)
class ClientState:
    """Representation of a connected OpenTTD client."""

    client_id: int
    name: str = ""
    company_id: Optional[int] = None

    @property
    def is_spectator(self) -> bool:
        """Return whether the client currently spectates."""

        return self.company_id is None


@dataclass(slots=True)
class CompanyState:
    """Representation of a company on the server."""

    company_id: int
    name: str = ""
    manager_name: str = ""
    passworded: bool = False

    def update_passworded(self, passworded: bool) -> None:
        """Update the cached password state."""

        self.passworded = passworded
