"""Abstractions over the pyOpenTTDAdmin client."""

from __future__ import annotations

import logging
from typing import Iterable

from pyopenttdadmin import Admin

LOGGER = logging.getLogger(__name__)


class AdminMessenger:
    """High level helper for sending messages and RCON commands."""

    def __init__(self, admin: Admin) -> None:
        self._admin = admin

    def send_private(self, client_id: int, message: str) -> None:
        if not message:
            return
        LOGGER.debug("Sending private message to client %%s", client_id)
        self._admin.send_private(message, client_id)

    def send_private_lines(self, client_id: int, lines: Iterable[str]) -> None:
        for line in lines:
            self.send_private(client_id, line)

    def send_company(self, company_id: int, message: str) -> None:
        if not message:
            return
        LOGGER.debug("Sending company message to %%s", company_id)
        self._admin.send_company(message, company_id)

    def send_broadcast(self, message: str) -> None:
        if not message:
            return
        LOGGER.debug("Sending broadcast message")
        self._admin.send_global(message)

    def set_company_password(self, company_id: int, password: str) -> None:
        LOGGER.info("Setting password for company %s", company_id)
        command = self._format_company_password_command(company_id, password)
        self._admin.send_rcon(command)

    def clear_company_password(self, company_id: int) -> None:
        LOGGER.info("Clearing password for company %s", company_id)
        command = f"company_pw {company_id} \"\""
        self._admin.send_rcon(command)

    def reset_company(self, company_id: int) -> None:
        LOGGER.info("Resetting company %s", company_id)
        self._admin.send_rcon(f"reset_company {company_id}")

    @staticmethod
    def _format_company_password_command(company_id: int, password: str) -> str:
        escaped = password.replace("\\", "\\\\").replace('"', '\\"')
        return f'company_pw {company_id} "{escaped}"'
