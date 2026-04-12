from __future__ import annotations

from core.command_parser import ParsedCommand
from server.routes.command import CommandRequest, _INTERACTIVE_SESSION, execute_command


def test_execute_command_closes_active_session() -> None:
    _INTERACTIVE_SESSION["retry_text"] = "onceki komut"
    _INTERACTIVE_SESSION["active_process_name"] = "chrome"

    response = execute_command(CommandRequest(text="tamam", approved=False))

    assert response.summary == "Aktif is akisi kapatildi."
    assert response.result == {"status": "closed"}
    assert _INTERACTIVE_SESSION["retry_text"] == ""
    assert _INTERACTIVE_SESSION["active_process_name"] == ""


def test_execute_command_resume_reuses_previous_command(monkeypatch) -> None:
    _INTERACTIVE_SESSION["retry_text"] = "onceki komut"
    _INTERACTIVE_SESSION["retry_approved"] = True

    def fake_parse(text: str, settings):
        assert text == "onceki komut"
        return ParsedCommand(action="system_status", confidence=0.9, params={}, workflow_profile="system_repair")

    monkeypatch.setattr("server.routes.command.parse_command", fake_parse)
    monkeypatch.setattr("server.routes.command.get_system_status", lambda: {"status": "ok"})

    response = execute_command(CommandRequest(text="tekrar dene", approved=False))

    assert response.action == "system_status"
    assert response.result == {"status": "ok"}


def test_execute_command_open_file_uses_native_open(monkeypatch) -> None:
    monkeypatch.setattr(
        "server.routes.command.parse_command",
        lambda text, settings: ParsedCommand(
            action="open_file",
            confidence=0.9,
            params={"query": "enerjisa", "location": "desktop"},
            workflow_profile="file_chain",
        ),
    )
    monkeypatch.setattr(
        "server.routes.command._search_with_fallback",
        lambda **kwargs: ([{"path": "C:/tmp/doc.pdf", "name": "doc.pdf", "modified_at": 1}], "desktop"),
    )
    monkeypatch.setattr(
        "server.routes.command.open_file_path",
        lambda file_path, allowed_folders=None: {"path": file_path, "name": "doc.pdf", "opened": True, "title_hint": "doc"},
    )

    response = execute_command(CommandRequest(text="dosyayi bul ve ac", approved=True))

    assert response.action == "open_file"
    assert response.result is not None
    assert response.result["opened"] is True
    assert "acildi" in response.summary


def test_execute_command_followup_uses_active_window_context(monkeypatch) -> None:
    _INTERACTIVE_SESSION["active_process_name"] = "chrome"
    _INTERACTIVE_SESSION["active_title_contains"] = "Enerjisa"

    monkeypatch.setattr(
        "server.routes.command.parse_command",
        lambda text, settings: ParsedCommand(
            action="click_ui",
            confidence=0.9,
            params={"text": "sayfanin ustundeki linke", "button": "left"},
            workflow_profile="app_control",
        ),
    )

    def fake_click_ui(**kwargs):
        assert kwargs["process_name"] == "chrome"
        assert kwargs["title_contains"] == "Enerjisa"
        return {"clicked": True, "process_name": "chrome", "title": "Enerjisa"}

    monkeypatch.setattr("server.routes.command.click_ui", fake_click_ui)

    response = execute_command(CommandRequest(text="sayfanin ustundeki linke tikla", approved=True))

    assert response.action == "click_ui"
    assert response.result is not None
    assert response.result["clicked"] is True


def test_execute_command_create_ticket_uses_native_ticket_store(monkeypatch) -> None:
    monkeypatch.setattr(
        "server.routes.command.parse_command",
        lambda text, settings: ParsedCommand(
            action="create_ticket",
            confidence=0.92,
            params={"title": "outlook mail gondermiyor", "description": "ticket ac outlook mail gondermiyor"},
            workflow_profile="system_repair",
        ),
    )
    monkeypatch.setattr("server.routes.command.create_support_ticket", lambda *args, **kwargs: 42)

    response = execute_command(CommandRequest(text="ticket ac outlook mail gondermiyor", approved=False))

    assert response.action == "create_ticket"
    assert response.result is not None
    assert response.result["ticket_id"] == 42
    assert "olusturuldu" in response.summary
