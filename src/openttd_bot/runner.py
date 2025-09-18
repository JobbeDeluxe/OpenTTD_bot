"""Runtime integration with the OpenTTD admin interface."""

from __future__ import annotations

import logging
import socket
import shutil
import subprocess
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


class InstrumentedAdmin(Admin):
    """Admin client with additional diagnostics for connection issues."""

    socket_timeout_seconds = 0.5

    def __init__(self, host: str, port: int) -> None:
        super().__init__(host, port)
        # ``Admin.__init__`` sets the socket timeout, store it for reference.
        try:
            timeout = self.socket.gettimeout()
        except OSError:
            timeout = None
        self.socket_timeout_seconds = float(timeout or 0.5)
        self.empty_read_count = 0
        self.protocol_received = False
        self.last_socket_error: str | None = None
        self.last_raw_bytes: bytes = b""

    # ------------------------------------------------------------------

    def mark_protocol_received(self) -> None:
        self.protocol_received = True
        self.empty_read_count = 0

    # ------------------------------------------------------------------

    def debug_state(self) -> str:
        parts = [
            f"protocol_received={self.protocol_received}",
            f"empty_reads={self.empty_read_count}",
        ]
        if self.last_socket_error:
            parts.append(f"last_socket_error={self.last_socket_error}")

        if self.last_raw_bytes:
            parts.append(f"last_bytes={self.last_raw_bytes.hex()}")

        try:
            remote = self.socket.getpeername()
            local = self.socket.getsockname()
        except OSError as exc:
            parts.append(f"peer=unavailable({exc})")
        else:
            parts.append(f"peer={remote}")
            parts.append(f"local={local}")

        parts.append(f"socket_timeout={self.socket_timeout_seconds}")
        return ", ".join(parts)

    # ------------------------------------------------------------------

    def _recv(self, size: int) -> bytes:  # noqa: D401 - inherited docstring
        try:
            data = self.socket.recv(size)
        except socket.timeout:
            if not self.protocol_received:
                self.empty_read_count += 1
                if LOGGER.isEnabledFor(logging.DEBUG):
                    LOGGER.debug(
                        "Admin socket timed out waiting for %s bytes (%s consecutive empty reads)",
                        size,
                        self.empty_read_count,
                    )
            return b""
        except OSError as exc:
            self.last_socket_error = f"{exc.__class__.__name__}: {exc}"
            LOGGER.warning("Socket error while reading admin data: %s", self.last_socket_error)
            raise

        self.last_socket_error = None

        if not data:
            LOGGER.warning(
                "Admin socket closed by remote host after %s consecutive empty reads",
                self.empty_read_count,
            )
            raise ConnectionAbortedError("Server closed the admin connection")

        if not self.protocol_received:
            if self.empty_read_count:
                if LOGGER.isEnabledFor(logging.DEBUG):
                    LOGGER.debug(
                        "Received %s bytes after %s empty reads while waiting for protocol packet",
                        len(data),
                        self.empty_read_count,
                    )
                self.empty_read_count = 0

            if LOGGER.isEnabledFor(logging.DEBUG):
                self.last_raw_bytes = data[:32]
                LOGGER.debug(
                    "Received %s raw bytes from admin socket: %s",
                    len(data),
                    self.last_raw_bytes.hex(),
                )
            else:
                self.last_raw_bytes = data[:32]
        else:
            self.last_raw_bytes = data[:32]

        return data


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
        with InstrumentedAdmin(self.config.host, self.config.admin_port) as admin:
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
                args=(admin, protocol_event),
                daemon=True,
            )
            watchdog.start()

            try:
                self._authenticate(admin)

                try:
                    admin.run()
                except ConnectionAbortedError:
                    if not protocol_event.is_set():
                        details = ""
                        if hasattr(admin, "debug_state"):
                            try:
                                details = f" ({admin.debug_state()})"
                            except Exception:  # pragma: no cover - defensive logging
                                LOGGER.debug("Failed to collect admin debug state", exc_info=True)
                        LOGGER.error(
                            "Admin connection closed before receiving protocol packet%s", details
                        )
                    raise
            finally:
                protocol_event.set()

    # ------------------------------------------------------------------

    def _handle_protocol(
        self, bot: BotCore, protocol_event: threading.Event
    ) -> Callable[[Admin, ProtocolPacket], None]:
        def handler(admin: Admin, packet: ProtocolPacket) -> None:
            LOGGER.info("Received protocol packet version %s", packet.version)
            protocol_event.set()
            if hasattr(admin, "mark_protocol_received"):
                try:
                    admin.mark_protocol_received()
                except Exception:  # pragma: no cover - defensive logging
                    LOGGER.debug("Failed to mark protocol as received", exc_info=True)

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

    def _authenticate(self, admin: Admin) -> None:
        """Send the initial admin login packet to authenticate with the server."""

        try:
            LOGGER.info("Authenticating as %s", self.config.bot_name)
            admin.login(self.config.bot_name, self.config.admin_password)
        except Exception:
            LOGGER.exception("Failed to send admin login packet")
            raise

    # ------------------------------------------------------------------

    def _protocol_watchdog(self, admin: Admin, protocol_event: threading.Event) -> None:
        wait_interval = max(1, PROTOCOL_WATCHDOG_INTERVAL_SECONDS)
        waited = wait_interval
        last_logged_empty_reads = -1

        while not protocol_event.wait(wait_interval):
            if waited == wait_interval:
                LOGGER.warning(
                    "Still waiting for initial protocol packet from %s:%s after %s seconds. "
                    "Verify that the OpenTTD server is reachable and that the admin port is enabled.",
                    self.config.host,
                    self.config.admin_port,
                    waited,
                )
                self._log_connectivity_probe()
            else:
                LOGGER.debug(
                    "Still waiting for initial protocol packet from %s:%s after %s seconds",
                    self.config.host,
                    self.config.admin_port,
                    waited,
                )
            last_logged_empty_reads = self._log_admin_socket_state(
                admin,
                waited,
                last_logged_empty_reads,
            )
            waited += wait_interval

    def _log_connectivity_probe(self) -> None:
        """Run a short netcat probe to help diagnose connectivity issues."""

        if shutil.which("nc") is None:
            LOGGER.info("Skipping netcat connectivity probe because 'nc' was not found in PATH")
            return

        command = ["nc", "-vz", str(self.config.host), str(self.config.admin_port)]
        LOGGER.info("Running netcat connectivity probe: %s", " ".join(command))

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            LOGGER.warning("Netcat connectivity probe timed out after 5 seconds")
            return
        except OSError as exc:
            LOGGER.warning("Failed to execute netcat connectivity probe: %s", exc)
            return

        if result.stdout:
            LOGGER.info("netcat stdout:\n%s", result.stdout.strip())
        if result.stderr:
            LOGGER.info("netcat stderr:\n%s", result.stderr.strip())

        LOGGER.info("netcat exited with return code %s", result.returncode)

    def _log_admin_socket_state(
        self,
        admin: Admin,
        waited_seconds: int,
        last_logged_empty_reads: int,
    ) -> int:
        """Log diagnostic information about the admin socket state."""

        empty_reads = getattr(admin, "empty_read_count", None)

        if empty_reads is not None:
            if last_logged_empty_reads == -1:
                if empty_reads:
                    LOGGER.warning(
                        "No data received from admin port after %s seconds (%s consecutive empty reads)",
                        waited_seconds,
                        empty_reads,
                    )
                else:
                    LOGGER.debug(
                        "Admin socket reported no empty reads after %s seconds", waited_seconds
                    )
            elif empty_reads != last_logged_empty_reads:
                LOGGER.debug(
                    "Still waiting for protocol packet: %s consecutive empty reads observed", empty_reads
                )

        if last_logged_empty_reads == -1 and hasattr(admin, "debug_state"):
            try:
                LOGGER.debug("Admin socket debug snapshot: %s", admin.debug_state())
            except Exception:  # pragma: no cover - defensive logging
                LOGGER.debug("Failed to capture admin socket debug state", exc_info=True)

        return empty_reads if empty_reads is not None else last_logged_empty_reads
