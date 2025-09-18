from __future__ import annotations

from openttd_bot.messenger import AdminMessenger


class DummyAdmin:
    def __init__(self) -> None:
        self.rcon_commands: list[str] = []

    def send_rcon(self, command: str) -> None:  # pragma: no cover - simple stub
        self.rcon_commands.append(command)


def test_rcon_commands_use_one_based_company_ids() -> None:
    admin = DummyAdmin()
    messenger = AdminMessenger(admin)  # type: ignore[arg-type]

    messenger.set_company_password(5, "secret")
    messenger.clear_company_password(5)
    messenger.reset_company(5)

    assert admin.rcon_commands == [
        'company_pw 6 "secret"',
        'company_pw 6 ""',
        'reset_company 6',
    ]
