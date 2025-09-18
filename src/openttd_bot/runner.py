"""Runtime integration with the OpenTTD admin interface."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from pyopenttdadmin import Admin
from pyopenttdadmin.enums import AdminUpdateFrequency, AdminUpdateType
from pyopenttdadmin.packet import (
    ChatPacket,
    ClientInfoPacket,
    ClientJoinPacket,
    ClientQuitPacket,
    ClientUpdatePacket,
    CompanyInfoPacket,
    CompanyNewPacket,
    CompanyRemovePacket,
    CompanyUpdatePacket,
    ProtocolPacket,
    ShutdownPacket,
    WelcomePacket,
)

from .config import BotConfig
from .core import BotCore
from .messages import MessageCatalog
from .messenger import AdminMessenger
from .state import StateStore

LOGGER = logging.getLogger(__name__)

PROTOCOL_WATCHDOG_INTERVAL_SECONDS = 10


class BotRunner:
    """Glue code between the Admin client and the bot core."""

    def __init__(self, config: BotConfig, messages: MessageCatalog, state_store: StateStore) -> None:
        self.config = config
        self.messages = messages
        self.state_store = state_store

    def run(self) -> None:
        """Run the bot forever, reconnecting on errors."""

        while True:
            try:
                self._run_session()
            except KeyboardInterrupt:  # pragma: no cover - handled by runner
                LOGGER.info("Interrupted by user")
                raise
            except Exception as exc:  # pragma: no cover - connection errors
                LOGGER.exception("Connection error: %s", exc)
                time.sleep(self.config.reconnect_delay_seconds)

    # ------------------------------------------------------------------

    def _run_session(self) -> None:
        LOGGER.info("Connecting to %s:%s", self.config.host, self.config.admin_port)
        with Admin(self.config.host, self.config.admin_port) as admin:
            messenger = AdminMessenger(admin)
            bot = BotCore(self.config, self.messages, self.state_store, messenger)
            protocol_event = threading.Event()

            # Register packet handlers
            admin.add_handler(ProtocolPacket)(self._handle_protocol(bot, protocol_event))
            admin.add_handler(WelcomePacket)(self._handle_welcome(bot))
            admin.add_handler(ClientJoinPacket)(lambda _admin, packet: bot.on_client_join(packet))
            admin.add_handler(ClientQuitPacket)(lambda _admin, packet: bot.on_client_quit(packet))
            admin.add_handler(ClientInfoPacket)(lambda _admin, packet: bot.on_client_info(packet))
            admin.add_handler(ClientUpdatePacket)(lambda _admin, packet: bot.on_client_update(packet))
            admin.add_handler(CompanyNewPacket)(lambda _admin, packet: bot.on_company_info(packet))
            admin.add_handler(CompanyInfoPacket)(lambda _admin, packet: bot.on_company_info(packet))
            admin.add_handler(CompanyUpdatePacket)(lambda _admin, packet: bot.on_company_update(packet))
            admin.add_handler(CompanyRemovePacket)(lambda _admin, packet: bot.on_company_remove(packet))
            admin.add_handler(ChatPacket)(lambda _admin, packet: bot.on_chat(packet))
            admin.add_handler(ShutdownPacket)(lambda _admin, packet: LOGGER.info("Server shutting down"))

            LOGGER.info("Waiting for server protocol packet")
            watchdog = threading.Thread(
                target=self._protocol_watchdog,
                name="protocol-watchdog",
                args=(protocol_event,),
                daemon=True,
            )
            watchdog.start()

            try:
                admin.run()
            finally:
                protocol_event.set()

    # ------------------------------------------------------------------

    def _handle_protocol(
        self, bot: BotCore, protocol_event: threading.Event
    ) -> Callable[[Admin, ProtocolPacket], None]:
        def handler(admin: Admin, packet: ProtocolPacket) -> None:
            LOGGER.info("Received protocol packet version %s", packet.version)
            protocol_event.set()
            admin.login(self.config.bot_name, self.config.admin_password)

        return handler

    def _handle_welcome(self, bot: BotCore) -> Callable[[Admin, WelcomePacket], None]:
        def handler(admin: Admin, packet: WelcomePacket) -> None:
            LOGGER.info("Logged in as %s", self.config.bot_name)
            bot.on_welcome(packet)
            admin.subscribe(AdminUpdateType.CLIENT_INFO, AdminUpdateFrequency.AUTOMATIC)
            admin.subscribe(AdminUpdateType.COMPANY_INFO, AdminUpdateFrequency.AUTOMATIC)
            admin.subscribe(AdminUpdateType.CHAT, AdminUpdateFrequency.AUTOMATIC)
            self._schedule_reapply(bot)

        return handler

    def _schedule_reapply(self, bot: BotCore) -> None:
        delay = max(0, self.config.startup_reapply_delay_seconds)
        if delay == 0:
            bot.reapply_stored_passwords()
            return

        def worker() -> None:
            LOGGER.info("Waiting %s seconds before reapplying passwords", delay)
            time.sleep(delay)
            bot.reapply_stored_passwords()

        thread = threading.Thread(target=worker, name="password-reapply", daemon=True)
        thread.start()

    # ------------------------------------------------------------------

    def _protocol_watchdog(self, protocol_event: threading.Event) -> None:
        wait_interval = max(1, PROTOCOL_WATCHDOG_INTERVAL_SECONDS)
        waited = wait_interval

        while not protocol_event.wait(wait_interval):
            if waited == wait_interval:
                LOGGER.warning(
                    "Still waiting for initial protocol packet from %s:%s after %s seconds. "
                    "Verify that the OpenTTD server is reachable and that the admin port is enabled.",
                    self.config.host,
                    self.config.admin_port,
                    waited,
                )
            else:
                LOGGER.debug(
                    "Still waiting for initial protocol packet from %s:%s after %s seconds",
                    self.config.host,
                    self.config.admin_port,
                    waited,
                )
            waited += wait_interval
