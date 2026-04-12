from __future__ import annotations

from core.command_parser import parse_command, route_to_workflow_profile
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


def test_parse_command_falls_back_when_gemini_raises(monkeypatch) -> None:
    def fail_parse(*, api_key: str, model: str, prompt: str):
        raise RuntimeError("Gemini unavailable")

    monkeypatch.setattr("core.command_parser.parse_command_with_gemini", fail_parse)

    parsed = parse_command(
        "gorunen pencereleri listele",
        AppSettings(gemini_api_key="test-key", gemini_model="gemini-test"),
    )

    assert parsed.action == "list_windows"


def test_parse_command_uses_high_confidence_fallback_before_gemini(monkeypatch) -> None:
    def fail_parse(*, api_key: str, model: str, prompt: str):
        raise AssertionError("Gemini cagrilmamali")

    monkeypatch.setattr("core.command_parser.parse_command_with_gemini", fail_parse)

    parsed = parse_command(
        "gorunen pencereleri listele",
        AppSettings(gemini_api_key="test-key", gemini_model="gemini-test"),
    )

    assert parsed.action == "list_windows"


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


def test_parse_command_falls_back_to_open_file_for_search_and_open_request() -> None:
    parsed = parse_command(
        "masaustundeki Enerjisa Citrix Kullanim Dokumani_V1 dosyasini bul ve ac",
        AppSettings(),
    )

    assert parsed.action == "open_file"
    assert parsed.params["location"] == "desktop"
    assert "enerjisa citrix kullanim dokumani_v1" in parsed.params["query"]


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


def test_parse_command_normalizes_common_typos_before_fallback() -> None:
    parsed = parse_command(
        "masa ütünde ki excel dosyalarini bul",
        AppSettings(),
    )

    assert parsed.action == "search_file"
    assert parsed.params["location"] == "desktop"
    assert parsed.params["extension"] == "xlsx"


def test_parse_command_routes_bulk_create_folder_and_move_to_unknown() -> None:
    parsed = parse_command(
        "Tüm excelleri 2026 exceller isminde bir klasör oluşturup o klasöre taşı",
        AppSettings(),
    )

    assert parsed.action == "unknown"
    assert parsed.confidence >= 0.8


def test_parse_command_routes_zip_folder_request_to_unknown() -> None:
    parsed = parse_command(
        "2026 exceller klasÃ¶rÃ¼nÃ¼ ziple",
        AppSettings(),
    )

    assert parsed.action == "unknown"
    assert parsed.confidence >= 0.8


def test_parse_command_move_uses_desktop_as_default_source_and_downloads_as_destination() -> None:
    parsed = parse_command(
        "masaustumdeki raporu downloads klasorune tasi",
        AppSettings(),
    )

    assert parsed.action == "move_file"
    assert parsed.params["location"] == "desktop"
    assert parsed.params["destination_location"] == "downloads"


def test_parse_command_routes_excel_editing_request_to_unknown() -> None:
    parsed = parse_command(
        "Excel calisma kitabi ac ve A sutununa Baslik olarak D.T B sutun basligina Sozlesme Hesabi yazip kaydet",
        AppSettings(),
    )

    assert parsed.action == "unknown"
    assert parsed.confidence >= 0.8


def test_parse_command_ticket_request_creates_ticket_action() -> None:
    parsed = parse_command(
        "ticket ac outlook mail gondermiyor",
        AppSettings(),
    )

    assert parsed.action == "create_ticket"
    assert parsed.params["title"] == "outlook mail gondermiyor"
    assert parsed.params["description"] == "ticket ac outlook mail gondermiyor"


def test_parse_command_click_ui_simplifies_long_pdf_sentence() -> None:
    parsed = parse_command(
        "simdi Enerjisa Citrix Kullanim Dokumani_V1 isimli PDF deki linke tikla",
        AppSettings(),
    )

    assert parsed.action == "click_ui"
    assert parsed.params["text"] == "link"


def test_route_to_workflow_profile_file_chain() -> None:
    assert route_to_workflow_profile("2026 exceller klasorunu ziple") == "file_chain"


def test_route_to_workflow_profile_excel_workflow() -> None:
    assert route_to_workflow_profile("Excel calisma kitabi ac ve A sutununa baslik yazip kaydet") == "excel_workflow"


def test_route_to_workflow_profile_app_control() -> None:
    assert route_to_workflow_profile("outlook penceresini bekle ve gonder butonuna tikla") == "app_control"


def test_parse_command_sets_workflow_profile() -> None:
    parsed = parse_command("2026 exceller klasorunu ziple", AppSettings())
    assert parsed.workflow_profile == "file_chain"
