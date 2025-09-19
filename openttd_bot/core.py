"""Core bot logic for handling events and commands."""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import Dict, Optional

from pyopenttdadmin.enums import Actions, ChatDestTypes

from .config import BotConfig
from .messages import MessageCatalog
from .messenger import AdminMessenger
from .models import ClientState, CompanyState, SPECTATOR_COMPANY_ID
from .state import StateStore

LOGGER = logging.getLogger(__name__)


class BotCore:
    """Encapsulates all stateful behaviour of the bot."""

    def __init__(
        self,
        config: BotConfig,
        messages: MessageCatalog,
        state_store: StateStore,
        messenger: AdminMessenger,
    ) -> None:
        self.config = config
        self.messages = messages
        self.state_store = state_store
        self.messenger = messenger
        self.clients: Dict[int, ClientState] = {}
        self.companies: Dict[int, CompanyState] = {}
        self.pending_resets: Dict[int, int] = {}
        self.server_name: Optional[str] = None
        self._welcome_sent: set[int] = set()
        self._last_password_application: Dict[int, float] = {}

    # ------------------------------------------------------------------
    # Event handling helpers
    # ------------------------------------------------------------------

    def on_welcome(self, packet: SimpleNamespace) -> None:
        """Remember server level metadata."""

        self.server_name = getattr(packet, "server_name", None)
        LOGGER.info("Connected to server: %s", self.server_name)

    def on_client_join(self, packet: SimpleNamespace) -> None:
        client_id = getattr(packet, "id", None)
        if client_id is None:
            return
        LOGGER.info("Client %s joined", client_id)

    def on_client_quit(self, packet: SimpleNamespace) -> None:
        client_id = getattr(packet, "id", None)
        if client_id is None:
            return
        LOGGER.info("Client %s left", client_id)
        self.clients.pop(client_id, None)
        self.pending_resets.pop(client_id, None)
        self._welcome_sent.discard(client_id)

    def on_client_info(self, packet: SimpleNamespace) -> None:
        client_id = getattr(packet, "id", None)
        if client_id is None:
            return

        client = self.clients.get(client_id)
        if client is None:
            client = ClientState(client_id=client_id)
            self.clients[client_id] = client

        client.name = getattr(packet, "name", client.name)
        company_id = self._normalise_company_id(getattr(packet, "company_id", None))
        client.company_id = company_id

        if client_id not in self._welcome_sent:
            self._welcome_sent.add(client_id)
            self._send_join_messages(client)

    def on_client_update(self, packet: SimpleNamespace) -> None:
        client_id = getattr(packet, "id", None)
        if client_id is None:
            return
        client = self.clients.setdefault(client_id, ClientState(client_id=client_id))
        client.name = getattr(packet, "name", client.name)
        previous_company = client.company_id
        company_id = self._normalise_company_id(getattr(packet, "company_id", None))
        client.company_id = company_id

        if previous_company != company_id and company_id is not None:
            LOGGER.info(
                "Client %s joined company %s",
                client_id,
                self._display_company_id(company_id),
            )
            self._send_password_instructions(client)

    def on_company_info(self, packet: SimpleNamespace) -> None:
        company_id = getattr(packet, "id", None)
        if company_id is None:
            return
        company = self.companies.get(company_id)
        if company is None:
            company = CompanyState(company_id=company_id)
            self.companies[company_id] = company

        company.name = (
            getattr(packet, "name", None)
            or company.name
            or self._default_company_name(company_id)
        )
        company.manager_name = getattr(packet, "manager_name", company.manager_name)
        passworded = bool(getattr(packet, "passworded", company.passworded))
        company.update_passworded(passworded)

        if not passworded:
            self._maybe_reapply_password(company_id, reason="company_info")

    def on_company_update(self, packet: SimpleNamespace) -> None:
        company_id = getattr(packet, "id", None)
        if company_id is None:
            return
        company = self.companies.setdefault(company_id, CompanyState(company_id=company_id))
        name = getattr(packet, "name", None)
        if name:
            company.name = name
        passworded = bool(getattr(packet, "passworded", company.passworded))
        company.update_passworded(passworded)
        if not passworded:
            self._maybe_reapply_password(company_id, reason="company_update")

    def on_company_remove(self, packet: SimpleNamespace) -> None:
        company_id = getattr(packet, "id", None)
        if company_id is None:
            return
        LOGGER.info("Company %s removed", self._display_company_id(company_id))
        self.companies.pop(company_id, None)
        self.state_store.clear_company_password(company_id)
        self._last_password_application.pop(company_id, None)

    # ------------------------------------------------------------------
    # Chat handling
    # ------------------------------------------------------------------

    def on_chat(self, packet: SimpleNamespace) -> None:
        action = getattr(packet, "action", None)
        desttype = getattr(packet, "desttype", None)
        if action not in {Actions.CHAT, Actions.CHAT_CLIENT, Actions.CHAT_COMPANY}:
            return
        if desttype not in {ChatDestTypes.BROADCAST, ChatDestTypes.CLIENT, ChatDestTypes.TEAM}:
            return

        raw_message = getattr(packet, "message", "")
        message = raw_message.strip()
        if not message.startswith(self.config.command_prefix):
            return

        client_id = getattr(packet, "id", None)
        if client_id is None:
            return
        client = self.clients.get(client_id)
        if client is None:
            LOGGER.debug("Ignoring command from unknown client %s", client_id)
            return

        command_line = message[len(self.config.command_prefix) :].strip()
        if not command_line:
            return

        parts = command_line.split(maxsplit=1)
        command = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""
        is_private = desttype == ChatDestTypes.CLIENT

        if command == "help":
            self._send_help(client)
        elif command == "rules":
            self._send_rules(client)
        elif command == "pw":
            self._handle_password_command(client, argument, is_private)
        elif command == "reset":
            self._handle_reset_command(client)
        elif command == "confirm":
            self._handle_confirm_command(client)
        elif command == "newgame":
            self._handle_newgame_command(client, argument)
        else:
            LOGGER.debug("Unknown command %s from client %s", command, client_id)

    # ------------------------------------------------------------------
    # Command implementations
    # ------------------------------------------------------------------

    def _send_help(self, client: ClientState) -> None:
        lines = self.messages.get_lines("help", client_name=client.name, bot_name=self.config.bot_name)
        if lines:
            self.messenger.send_private_lines(client.client_id, lines)

    def _send_rules(self, client: ClientState) -> None:
        lines = self.messages.get_lines("rules", client_name=client.name, bot_name=self.config.bot_name)
        if lines:
            self.messenger.send_private_lines(client.client_id, lines)

    def _send_join_messages(self, client: ClientState) -> None:
        context = {
            "client_name": client.name or f"Spieler {client.client_id}",
            "bot_name": self.config.bot_name,
            "server_name": self.server_name or "OpenTTD",
        }
        combined_lines: list[str] = []
        for key in ("welcome", "help", "rules"):
            combined_lines.extend(self.messages.get_lines(key, **context))

        blocks = [block for block in self.messages.merge_sections(combined_lines) if block]
        if not blocks:
            return

        lines_to_send: list[str] = []
        for block in blocks:
            for line in block.split("\n"):
                if line.strip():
                    lines_to_send.append(line)

        if lines_to_send:
            self.messenger.send_private_lines(client.client_id, lines_to_send)

    def _send_password_instructions(self, client: ClientState) -> None:
        context = {
            "client_name": client.name,
            "bot_name": self.config.bot_name,
            "company_name": self._company_display_name(client.company_id),
        }
        lines = self.messages.get_lines("password_instructions", **context)
        if lines:
            self.messenger.send_private_lines(client.client_id, lines)

    def _handle_password_command(self, client: ClientState, argument: str, is_private: bool) -> None:
        if not is_private:
            lines = self.messages.get_lines(
                "password_whisper_only", bot_name=self.config.bot_name
            )
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            return

        if client.is_spectator or client.company_id is None:
            lines = self.messages.get_lines("password_not_in_company")
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            return

        if not argument:
            lines = self.messages.get_lines("password_missing_argument")
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            return

        company_id = client.company_id
        company_name = self._company_display_name(company_id)

        lowered = argument.lower()
        if lowered in {"clear", "reset", "remove", "delete", "none", "leer"}:
            self.messenger.clear_company_password(company_id)
            self.state_store.clear_company_password(company_id)
            self._last_password_application.pop(company_id, None)
            lines = self.messages.get_lines("password_clear_success", company_name=company_name)
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            return

        if any(ch in argument for ch in {"\n", "\r"}):
            lines = self.messages.get_lines("password_invalid")
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            return

        self.state_store.set_company_password(company_id, argument)
        self._apply_company_password(company_id, argument, notify=False)
        lines = self.messages.get_lines("password_set_success", company_name=company_name)
        if lines:
            self.messenger.send_private_lines(client.client_id, lines)

    def _handle_reset_command(self, client: ClientState) -> None:
        if client.company_id is None:
            lines = self.messages.get_lines("reset_not_in_company")
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            return

        self.pending_resets[client.client_id] = client.company_id
        company_name = self._company_display_name(client.company_id)
        lines = self.messages.get_lines("reset_prompt", company_name=company_name)
        if lines:
            self.messenger.send_private_lines(client.client_id, lines)

    def _handle_confirm_command(self, client: ClientState) -> None:
        pending_company = self.pending_resets.get(client.client_id)
        if pending_company is None:
            lines = self.messages.get_lines("reset_no_pending")
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            return

        company_name = self._company_display_name(pending_company)

        if client.company_id == pending_company:
            lines = self.messages.get_lines(
                "reset_still_in_company", company_name=company_name
            )
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            return

        if client.company_id not in {None, pending_company}:
            lines = self.messages.get_lines(
                "reset_wrong_company", company_name=company_name
            )
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            self.pending_resets.pop(client.client_id, None)
            return

        self.pending_resets.pop(client.client_id, None)
        self.messenger.reset_company(pending_company)
        lines = self.messages.get_lines("reset_confirmed", company_name=company_name)
        if lines:
            self.messenger.send_private_lines(client.client_id, lines)

    def _handle_newgame_command(self, client: ClientState, argument: str) -> None:
        if not argument:
            lines = self.messages.get_lines("newgame_missing_password")
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            return

        if argument != self.config.admin_password:
            lines = self.messages.get_lines("newgame_invalid_password")
            if lines:
                self.messenger.send_private_lines(client.client_id, lines)
            return

        self._clear_all_company_passwords()
        self.pending_resets.clear()
        self.messenger.restart_game()

        lines = self.messages.get_lines("newgame_started")
        if lines:
            self.messenger.send_private_lines(client.client_id, lines)

    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    def _apply_company_password(self, company_id: int, password: str, notify: bool) -> None:
        now = time.monotonic()
        self._last_password_application[company_id] = now
        try:
            self.messenger.set_company_password(company_id, password)
        finally:
            company = self.companies.get(company_id)
            if company is not None:
                company.passworded = True
        if notify:
            self._notify_company_members(company_id, "company_password_reapplied")

    def _maybe_reapply_password(self, company_id: int, reason: str) -> None:
        password = self.state_store.get_company_password(company_id)
        if not password:
            return
        last = self._last_password_application.get(company_id)
        now = time.monotonic()
        if last is not None and now - last < 2.0:
            LOGGER.debug(
                "Skip password reapply for company %s due to cooldown",
                self._display_company_id(company_id),
            )
            return
        LOGGER.info(
            "Re-applying password for company %s (reason: %s)",
            self._display_company_id(company_id),
            reason,
        )
        self._apply_company_password(company_id, password, notify=True)

    def _notify_company_members(self, company_id: int, message_key: str) -> None:
        company_name = self._company_display_name(company_id)
        lines = self.messages.get_lines(message_key, company_name=company_name)
        if not lines:
            return
        for client in self.clients.values():
            if client.company_id == company_id:
                self.messenger.send_private_lines(client.client_id, lines)

    def _clear_all_company_passwords(self) -> None:
        stored_company_ids = [company_id for company_id, _ in self.state_store.iter_company_passwords()]
        all_company_ids = set(stored_company_ids)
        all_company_ids.update(self.companies.keys())

        for company_id in sorted(all_company_ids):
            LOGGER.info(
                "Clearing password for company %s before starting new game",
                self._display_company_id(company_id),
            )
            self.messenger.clear_company_password(company_id)
            self._last_password_application.pop(company_id, None)
            company = self.companies.get(company_id)
            if company is not None:
                company.passworded = False

        self.state_store.clear_all_company_passwords()

    def reapply_stored_passwords(self) -> None:
        """Reapply all stored passwords via RCON."""

        for company_id, password in self.state_store.iter_company_passwords():
            LOGGER.info(
                "Re-applying stored password for company %s",
                self._display_company_id(company_id),
            )
            self._apply_company_password(company_id, password, notify=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_company_id(company_id: Optional[int]) -> Optional[int]:
        if company_id is None:
            return None
        if company_id == SPECTATOR_COMPANY_ID:
            return None
        return company_id

    @staticmethod
    def _default_company_name(company_id: int) -> str:
        return f"Firma #{company_id + 1}"

    @staticmethod
    def _display_company_id(company_id: int) -> int:
        return company_id + 1

    def _company_display_name(self, company_id: Optional[int]) -> str:
        if company_id is None:
            return "Firma"
        company = self.companies.get(company_id)
        if company and company.name:
            return company.name
        return self._default_company_name(company_id)
