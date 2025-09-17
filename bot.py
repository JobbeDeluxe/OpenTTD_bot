"""Entry point for running the OpenTTD helper bot."""

from __future__ import annotations

import logging
import sys

from openttd_bot.config import BotConfig
from openttd_bot.messages import MessageCatalog
from openttd_bot.runner import BotRunner
from openttd_bot.state import StateStore


def configure_logging() -> None:
    level_name = "INFO"
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> int:
    configure_logging()
    config = BotConfig.from_env()
    messages = MessageCatalog.load(config.messages_file)
    state_store = StateStore(config.state_file)

    runner = BotRunner(config, messages, state_store)
    runner.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
