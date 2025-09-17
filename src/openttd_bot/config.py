"""Configuration helpers for the OpenTTD helper bot."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(slots=True)
class BotConfig:
    """Runtime configuration for the bot."""

    host: str
    admin_port: int
    admin_password: str
    bot_name: str
    command_prefix: str
    state_file: Path
    messages_file: Path
    startup_reapply_delay_seconds: int
    reconnect_delay_seconds: int = 5

    @classmethod
    def from_env(cls) -> "BotConfig":
        """Create a configuration object from environment variables."""

        host = os.getenv("OTTD_HOST", "127.0.0.1")
        port = int(os.getenv("OTTD_ADMIN_PORT", "3977"))
        admin_password = os.getenv("OTTD_ADMIN_PASSWORD", "")
        if not admin_password:
            raise ValueError("Environment variable OTTD_ADMIN_PASSWORD must be set")

        bot_name = os.getenv("BOT_NAME", "ServerBot")
        command_prefix = os.getenv("COMMAND_PREFIX", "!")
        state_file = Path(os.getenv("STATE_FILE", "state.json")).expanduser().resolve()
        messages_file = Path(os.getenv("MESSAGES_FILE", "messages.json")).expanduser().resolve()
        startup_delay = int(os.getenv("STARTUP_REAPPLY_DELAY_SECONDS", "5"))
        reconnect_delay = int(os.getenv("RECONNECT_DELAY_SECONDS", "5"))

        return cls(
            host=host,
            admin_port=port,
            admin_password=admin_password,
            bot_name=bot_name,
            command_prefix=command_prefix,
            state_file=state_file,
            messages_file=messages_file,
            startup_reapply_delay_seconds=startup_delay,
            reconnect_delay_seconds=reconnect_delay,
        )
