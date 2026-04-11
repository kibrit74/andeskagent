from __future__ import annotations

from core.command_parser import parse_command
from core.config import AppSettings


def test_parse_command_uses_gemini_payload(monkeypatch) -> None:
    def fake_parse(*, api_key: str, model: str, prompt: str):
        assert api_key == "test-key"
        assert model == "gemini-test"
        assert "mart takipler" in prompt

        class Payload:
            action = "send_file"
            params = {"query": "mart takipler", "location": "desktop", "extension": ".xlsx"}
            confidence = 0.93

        return Payload()

    monkeypatch.setattr("core.command_parser.parse_command_with_gemini", fake_parse)

    parsed = parse_command(
        "masaustundeki mart takipler dosyasini bana gonder",
        AppSettings(
            gemini_api_key="test-key",
            gemini_model="gemini-test",
            allowed_scripts=["dns_flush"],
        ),
    )

    assert parsed.action == "send_file"
    assert parsed.params == {
        "query": "mart takipler",
        "location": "desktop",
        "extension": "xlsx",
    }
    assert parsed.confidence == 0.93


def test_parse_command_unknown_clears_irrelevant_params(monkeypatch) -> None:
    def fake_parse(*, api_key: str, model: str, prompt: str):
        class Payload:
            action = "unknown"
            params = {"query": "sil system32"}
            confidence = 0.1

        return Payload()

    monkeypatch.setattr("core.command_parser.parse_command_with_gemini", fake_parse)

    parsed = parse_command(
        "system32'yi sil",
        AppSettings(gemini_api_key="test-key", gemini_model="gemini-test"),
    )

    assert parsed.action == "unknown"
    assert parsed.params == {}


def test_parse_command_falls_back_without_gemini_key_for_status() -> None:
    parsed = parse_command(
        "sistem durumunu goster",
        AppSettings(),
    )

    assert parsed.action == "system_status"
    assert parsed.params == {}
    assert parsed.confidence > 0.5


def test_parse_command_falls_back_without_gemini_key_for_file_search() -> None:
    parsed = parse_command(
        "masaustumdeki excel dosyalarini bul",
        AppSettings(),
    )

    assert parsed.action == "search_file"
    assert parsed.params["location"] == "desktop"
    assert parsed.params["extension"] == "xlsx"


def test_parse_command_keeps_recipient_for_send_file(monkeypatch) -> None:
    def fake_parse(*, api_key: str, model: str, prompt: str):
        class Payload:
            action = "send_file"
            params = {
                "query": "Indirim Maili",
                "location": "desktop",
                "extension": "xlsx",
                "recipient": "yavuzob@gmail.com",
            }
            confidence = 0.95

        return Payload()

    monkeypatch.setattr("core.command_parser.parse_command_with_gemini", fake_parse)

    parsed = parse_command(
        "Indirim Maili excelini yavuzob@gmail.com adresine gonder",
        AppSettings(gemini_api_key="test-key", gemini_model="gemini-test"),
    )

    assert parsed.action == "send_file"
    assert parsed.params["recipient"] == "yavuzob@gmail.com"


def test_parse_command_fallback_extracts_recipient() -> None:
    parsed = parse_command(
        "Indirim Maili excelini yavuzob@gmail.com adresine gonder",
        AppSettings(),
    )

    assert parsed.action == "send_file"
    assert parsed.params["recipient"] == "yavuzob@gmail.com"
