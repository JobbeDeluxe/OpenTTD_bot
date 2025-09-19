from __future__ import annotations

from types import SimpleNamespace
from typing import List, Tuple

import pytest

from openttd_bot.config import BotConfig
from openttd_bot.core import BotCore
from openttd_bot.messages import DEFAULT_MESSAGES, MessageCatalog
from openttd_bot.models import SPECTATOR_COMPANY_ID
from openttd_bot.state import StateStore
from pyopenttdadmin.enums import Actions, ChatDestTypes


class FakeMessenger:
    def __init__(self) -> None:
        self.private_messages: List[Tuple[int, str]] = []
        self.company_messages: List[Tuple[int, str]] = []
        self.broadcasts: List[str] = []
        self.commands: List[Tuple[str, int, str | None]] = []

    def send_private(self, client_id: int, message: str) -> None:
        self.private_messages.append((client_id, message))

    def send_private_lines(self, client_id: int, lines) -> None:
        for line in lines:
            self.send_private(client_id, line)

    def send_company(self, company_id: int, message: str) -> None:
        self.company_messages.append((company_id, message))

    def send_broadcast(self, message: str) -> None:
        self.broadcasts.append(message)

    def set_company_password(self, company_id: int, password: str) -> None:
        self.commands.append(("set_pw", company_id, password))

    def clear_company_password(self, company_id: int) -> None:
        self.commands.append(("clear_pw", company_id, None))

    def reset_company(self, company_id: int) -> None:
        self.commands.append(("reset", company_id, None))

    def restart_game(self) -> None:
        self.commands.append(("restart", None, None))

    def reset_messages(self) -> None:
        self.private_messages.clear()
        self.company_messages.clear()
        self.broadcasts.clear()
        self.commands.clear()


@pytest.fixture
def bot(tmp_path):
    config = BotConfig(
        host="localhost",
        admin_port=3977,
        admin_password="admin",
        bot_name="ServerBot",
        command_prefix="!",
        state_file=tmp_path / "state.json",
        messages_file=tmp_path / "messages.json",
        startup_reapply_delay_seconds=0,
        reconnect_delay_seconds=5,
    )
    messages = MessageCatalog(dict(DEFAULT_MESSAGES))
    state_store = StateStore(config.state_file)
    messenger = FakeMessenger()
    core = BotCore(config, messages, state_store, messenger)  # type: ignore[arg-type]
    return core, messenger, state_store


def make_chat(client_id: int, message: str, dest: ChatDestTypes = ChatDestTypes.BROADCAST):
    return SimpleNamespace(
        action=Actions.CHAT if dest != ChatDestTypes.CLIENT else Actions.CHAT_CLIENT,
        desttype=dest,
        id=client_id,
        message=message,
        money=0,
    )


def test_merge_sections_combines_language_blocks():
    catalog = MessageCatalog(dict(DEFAULT_MESSAGES))
    lines = []
    lines.extend(catalog.get_lines("welcome", client_name="Alice", bot_name="ServerBot"))
    lines.extend(catalog.get_lines("help", bot_name="ServerBot"))
    lines.extend(catalog.get_lines("rules"))

    merged = catalog.merge_sections(lines)

    assert merged.count("---------------------[ENG]---------------------") == 1
    assert merged.count("---------------------[DE]---------------------") == 1

    eng_index = merged.index("---------------------[ENG]---------------------")
    de_index = merged.index("---------------------[DE]---------------------")
    assert eng_index < de_index

    eng_block = " ".join(merged[eng_index + 1 : de_index])
    de_block = " ".join(merged[de_index + 1 :])
    assert "Welcome Alice!" in eng_block
    assert "Available commands" in eng_block
    assert "Willkommen Alice!" in de_block
    assert "Verfügbare Befehle" in de_block


def test_join_sends_welcome_help_and_rules(bot):
    core, messenger, _ = bot
    core.on_welcome(SimpleNamespace(server_name="TestServer"))
    core.on_client_info(SimpleNamespace(id=1, name="Alice", company_id=SPECTATOR_COMPANY_ID))
    bot_name = core.config.bot_name
    expected_lines = []
    expected_lines.extend(
        core.messages.get_lines("welcome", client_name="Alice", bot_name=bot_name)
    )
    expected_lines.extend(core.messages.get_lines("help", bot_name=bot_name))
    expected_lines.extend(core.messages.get_lines("rules"))
    expected_blocks = core.messages.merge_sections(expected_lines)
    expected = [(1, block) for block in expected_blocks]
    assert messenger.private_messages[: len(expected)] == expected


def test_help_command_sends_help(bot):
    core, messenger, _ = bot
    core.on_client_info(SimpleNamespace(id=1, name="Alice", company_id=SPECTATOR_COMPANY_ID))
    messenger.reset_messages()
    core.on_chat(make_chat(1, "!help"))
    bot_name = core.config.bot_name
    expected = [
        (1, line) for line in core.messages.get_lines("help", bot_name=bot_name)
    ]
    assert messenger.private_messages == expected


def test_password_requires_private(bot):
    core, messenger, state_store = bot
    core.on_company_info(SimpleNamespace(id=3, name="Firma 3", manager_name="", passworded=False))
    core.on_client_info(SimpleNamespace(id=5, name="Bob", company_id=3))
    messenger.reset_messages()
    core.on_chat(make_chat(5, "!pw geheim", ChatDestTypes.BROADCAST))
    bot_name = core.config.bot_name
    expected = [
        (5, line)
        for line in core.messages.get_lines(
            "password_whisper_only", bot_name=bot_name
        )
    ]
    assert messenger.private_messages == expected
    assert state_store.get_company_password(3) is None
    assert messenger.commands == []


def test_password_private_sets_and_persists(bot):
    core, messenger, state_store = bot
    core.on_company_info(SimpleNamespace(id=2, name="Firma 2", manager_name="", passworded=False))
    core.on_client_info(SimpleNamespace(id=7, name="Cara", company_id=2))
    messenger.reset_messages()
    core.on_chat(make_chat(7, "!pw geheim", ChatDestTypes.CLIENT))
    assert state_store.get_company_password(2) == "geheim"
    assert ("set_pw", 2, "geheim") in messenger.commands
    expected = [
        (7, line)
        for line in core.messages.get_lines(
            "password_set_success", company_name="Firma 2"
        )
    ]
    assert messenger.private_messages[-len(expected) :] == expected


def test_password_clear(bot):
    core, messenger, state_store = bot
    core.on_company_info(SimpleNamespace(id=4, name="Firma 4", manager_name="", passworded=True))
    core.on_client_info(SimpleNamespace(id=8, name="Dora", company_id=4))
    state_store.set_company_password(4, "alt")
    messenger.reset_messages()
    core.on_chat(make_chat(8, "!pw clear", ChatDestTypes.CLIENT))
    assert state_store.get_company_password(4) is None
    assert ("clear_pw", 4, None) in messenger.commands
    expected = [
        (8, line)
        for line in core.messages.get_lines(
            "password_clear_success", company_name="Firma 4"
        )
    ]
    assert messenger.private_messages[-len(expected) :] == expected


def test_reset_and_confirm(bot):
    core, messenger, state_store = bot
    core.on_company_info(SimpleNamespace(id=6, name="Firma 6", manager_name="", passworded=True))
    core.on_client_info(SimpleNamespace(id=9, name="Eve", company_id=6))
    messenger.reset_messages()
    core.on_chat(make_chat(9, "!reset"))
    expected_prompt = [
        (9, line)
        for line in core.messages.get_lines(
            "reset_prompt", company_name="Firma 6"
        )
    ]
    assert messenger.private_messages[: len(expected_prompt)] == expected_prompt
    core.on_client_update(SimpleNamespace(id=9, name="Eve", company_id=SPECTATOR_COMPANY_ID))
    core.on_chat(make_chat(9, "!confirm"))
    assert ("reset", 6, None) in messenger.commands
    expected_confirm = [
        (9, line)
        for line in core.messages.get_lines(
            "reset_confirmed", company_name="Firma 6"
        )
    ]
    assert messenger.private_messages[-len(expected_confirm) :] == expected_confirm


def test_reset_confirm_requires_leaving_company(bot):
    core, messenger, _ = bot
    core.on_company_info(SimpleNamespace(id=10, name="Firma 10", manager_name="", passworded=True))
    core.on_client_info(SimpleNamespace(id=11, name="Fred", company_id=10))
    messenger.reset_messages()
    core.on_chat(make_chat(11, "!reset"))
    core.on_chat(make_chat(11, "!confirm"))
    expected = [
        (11, line)
        for line in core.messages.get_lines(
            "reset_still_in_company", company_name="Firma 10"
        )
    ]
    assert messenger.private_messages[-len(expected) :] == expected
    assert not any(cmd for cmd in messenger.commands if cmd[0] == "reset")


def test_reset_confirm_cancelled_in_other_company(bot):
    core, messenger, _ = bot
    core.on_company_info(SimpleNamespace(id=20, name="Firma 20", manager_name="", passworded=True))
    core.on_company_info(SimpleNamespace(id=21, name="Firma 21", manager_name="", passworded=True))
    core.on_client_info(SimpleNamespace(id=12, name="Gina", company_id=20))
    messenger.reset_messages()
    core.on_chat(make_chat(12, "!reset"))
    core.on_client_update(SimpleNamespace(id=12, name="Gina", company_id=21))
    core.on_chat(make_chat(12, "!confirm"))
    expected = [
        (12, line)
        for line in core.messages.get_lines(
            "reset_wrong_company", company_name="Firma 20"
        )
    ]
    assert messenger.private_messages[-len(expected) :] == expected
    assert not any(cmd for cmd in messenger.commands if cmd[0] == "reset")


def test_reapply_password_on_company_info(bot):
    core, messenger, state_store = bot
    state_store.set_company_password(12, "schutz")
    core.on_client_info(SimpleNamespace(id=13, name="Gina", company_id=12))
    messenger.reset_messages()
    core.on_company_info(SimpleNamespace(id=12, name="Firma 12", manager_name="", passworded=False))
    assert ("set_pw", 12, "schutz") in messenger.commands
    expected = [
        (13, line)
        for line in core.messages.get_lines(
            "company_password_reapplied", company_name="Firma 12"
        )
    ]
    assert messenger.private_messages[-len(expected) :] == expected


def test_reapply_all_passwords(bot):
    core, messenger, state_store = bot
    state_store.set_company_password(20, "eins")
    state_store.set_company_password(21, "zwei")
    core.reapply_stored_passwords()
    assert ("set_pw", 20, "eins") in messenger.commands
    assert ("set_pw", 21, "zwei") in messenger.commands


def test_newgame_requires_password(bot):
    core, messenger, _ = bot
    core.on_client_info(SimpleNamespace(id=30, name="Admin", company_id=SPECTATOR_COMPANY_ID))

    messenger.reset_messages()
    core.on_chat(make_chat(30, "!newgame", ChatDestTypes.CLIENT))
    expected_missing = [
        (30, line)
        for line in core.messages.get_lines("newgame_missing_password")
    ]
    assert messenger.private_messages == expected_missing
    assert messenger.commands == []

    messenger.reset_messages()
    core.on_chat(make_chat(30, "!newgame falsch", ChatDestTypes.CLIENT))
    expected_invalid = [
        (30, line)
        for line in core.messages.get_lines("newgame_invalid_password")
    ]
    assert messenger.private_messages == expected_invalid
    assert messenger.commands == []


def test_newgame_clears_passwords_and_restarts(bot):
    core, messenger, state_store = bot
    core.on_company_info(SimpleNamespace(id=0, name="Firma 1", manager_name="", passworded=True))
    core.on_company_info(SimpleNamespace(id=1, name="Firma 2", manager_name="", passworded=True))
    state_store.set_company_password(0, "secret")
    core.on_client_info(SimpleNamespace(id=31, name="Admin", company_id=SPECTATOR_COMPANY_ID))

    messenger.reset_messages()
    core.on_chat(make_chat(31, "!newgame admin", ChatDestTypes.CLIENT))

    assert ("clear_pw", 0, None) in messenger.commands
    assert ("clear_pw", 1, None) in messenger.commands
    assert ("restart", None, None) in messenger.commands
    assert list(state_store.iter_company_passwords()) == []
    expected_started = [
        (31, line)
        for line in core.messages.get_lines("newgame_started")
    ]
    assert messenger.private_messages[-len(expected_started) :] == expected_started
