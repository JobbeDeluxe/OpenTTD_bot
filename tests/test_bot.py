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


def test_join_sends_welcome_help_and_rules(bot):
    core, messenger, _ = bot
    core.on_welcome(SimpleNamespace(server_name="TestServer"))
    core.on_client_info(SimpleNamespace(id=1, name="Alice", company_id=SPECTATOR_COMPANY_ID))
    assert messenger.private_messages[:12] == [
        (1, "[DE] Willkommen Alice!"),
        (1, "[EN] Welcome Alice!"),
        (1, "[DE] Dieser Server wird von ServerBot betreut."),
        (1, "[EN] This server is maintained by ServerBot."),
        (1, "[DE] Verfügbare Befehle: !help, !rules, !pw <passwort>, !reset, !confirm."),
        (1, "[EN] Available commands: !help, !rules, !pw <password>, !reset, !confirm."),
        (1, "[DE] Nutze /whisper ServerBot !pw <passwort>, damit dein Passwort privat bleibt."),
        (1, "[EN] Use /whisper ServerBot !pw <password> to keep your password private."),
        (1, "[DE] 1. Respektiere andere Spieler."),
        (1, "[EN] 1. Respect other players."),
        (1, "[DE] 2. Blockiere keine Strecken."),
        (1, "[EN] 2. Do not block tracks."),
    ]


def test_help_command_sends_help(bot):
    core, messenger, _ = bot
    core.on_client_info(SimpleNamespace(id=1, name="Alice", company_id=SPECTATOR_COMPANY_ID))
    messenger.reset_messages()
    core.on_chat(make_chat(1, "!help"))
    assert messenger.private_messages == [
        (1, "[DE] Verfügbare Befehle: !help, !rules, !pw <passwort>, !reset, !confirm."),
        (1, "[EN] Available commands: !help, !rules, !pw <password>, !reset, !confirm."),
        (1, "[DE] Nutze /whisper ServerBot !pw <passwort>, damit dein Passwort privat bleibt."),
        (1, "[EN] Use /whisper ServerBot !pw <password> to keep your password private."),
    ]


def test_password_requires_private(bot):
    core, messenger, state_store = bot
    core.on_company_info(SimpleNamespace(id=3, name="Firma 3", manager_name="", passworded=False))
    core.on_client_info(SimpleNamespace(id=5, name="Bob", company_id=3))
    messenger.reset_messages()
    core.on_chat(make_chat(5, "!pw geheim", ChatDestTypes.BROADCAST))
    assert messenger.private_messages == [
        (5, "[DE] Bitte sende Firmenpasswörter nur per /whisper ServerBot !pw <passwort>, nicht im öffentlichen Chat."),
        (5, "[EN] Please submit company passwords only via /whisper ServerBot !pw <password>, never in public chat."),
    ]
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
    assert messenger.private_messages[-2:] == [
        (7, "[DE] Passwort für Firma Firma 2 wurde gespeichert."),
        (7, "[EN] Password for company Firma 2 has been saved."),
    ]


def test_password_clear(bot):
    core, messenger, state_store = bot
    core.on_company_info(SimpleNamespace(id=4, name="Firma 4", manager_name="", passworded=True))
    core.on_client_info(SimpleNamespace(id=8, name="Dora", company_id=4))
    state_store.set_company_password(4, "alt")
    messenger.reset_messages()
    core.on_chat(make_chat(8, "!pw clear", ChatDestTypes.CLIENT))
    assert state_store.get_company_password(4) is None
    assert ("clear_pw", 4, None) in messenger.commands
    assert messenger.private_messages[-2:] == [
        (8, "[DE] Passwort für Firma Firma 4 wurde entfernt."),
        (8, "[EN] Password for company Firma 4 has been removed."),
    ]


def test_reset_and_confirm(bot):
    core, messenger, state_store = bot
    core.on_company_info(SimpleNamespace(id=6, name="Firma 6", manager_name="", passworded=True))
    core.on_client_info(SimpleNamespace(id=9, name="Eve", company_id=6))
    messenger.reset_messages()
    core.on_chat(make_chat(9, "!reset"))
    assert messenger.private_messages[:4] == [
        (9, "[DE] Du möchtest Firma Firma 6 zurücksetzen."),
        (9, "[EN] You want to reset company Firma 6."),
        (9, "[DE] Verlasse zuerst die Firma (z. B. Zuschauer) und sende dann !confirm."),
        (9, "[EN] Leave the company first (e.g. become a spectator) and then send !confirm."),
    ]
    core.on_client_update(SimpleNamespace(id=9, name="Eve", company_id=SPECTATOR_COMPANY_ID))
    core.on_chat(make_chat(9, "!confirm"))
    assert ("reset", 6, None) in messenger.commands
    assert messenger.private_messages[-2:] == [
        (9, "[DE] Firma Firma 6 wurde zurückgesetzt."),
        (9, "[EN] Company Firma 6 has been reset."),
    ]


def test_reset_confirm_requires_leaving_company(bot):
    core, messenger, _ = bot
    core.on_company_info(SimpleNamespace(id=10, name="Firma 10", manager_name="", passworded=True))
    core.on_client_info(SimpleNamespace(id=11, name="Fred", company_id=10))
    messenger.reset_messages()
    core.on_chat(make_chat(11, "!reset"))
    core.on_chat(make_chat(11, "!confirm"))
    assert messenger.private_messages[-2:] == [
        (11, "[DE] Du befindest dich noch in Firma Firma 10. Verlasse sie zuerst und sende dann !confirm."),
        (11, "[EN] You are still in company Firma 10. Leave it first and then send !confirm."),
    ]
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
    assert messenger.private_messages[-2:] == [
        (
            12,
            "[DE] Deine Reset-Anfrage bezog sich auf Firma Firma 20. Bitte sende !reset erneut in der gewünschten Firma.",
        ),
        (
            12,
            "[EN] Your reset request was for company Firma 20. Please use !reset again in the company you want to reset.",
        ),
    ]
    assert not any(cmd for cmd in messenger.commands if cmd[0] == "reset")


def test_reapply_password_on_company_info(bot):
    core, messenger, state_store = bot
    state_store.set_company_password(12, "schutz")
    core.on_client_info(SimpleNamespace(id=13, name="Gina", company_id=12))
    messenger.reset_messages()
    core.on_company_info(SimpleNamespace(id=12, name="Firma 12", manager_name="", passworded=False))
    assert ("set_pw", 12, "schutz") in messenger.commands
    assert messenger.private_messages[-2:] == [
        (13, "[DE] Das gespeicherte Passwort für Firma Firma 12 wurde erneut gesetzt."),
        (13, "[EN] The stored password for company Firma 12 has been applied again."),
    ]


def test_reapply_all_passwords(bot):
    core, messenger, state_store = bot
    state_store.set_company_password(20, "eins")
    state_store.set_company_password(21, "zwei")
    core.reapply_stored_passwords()
    assert ("set_pw", 20, "eins") in messenger.commands
    assert ("set_pw", 21, "zwei") in messenger.commands
