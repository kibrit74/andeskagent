from __future__ import annotations

import json
import subprocess

from adapters import desktop_adapter


def test_read_screen_fast_skips_screenshot_and_ocr(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop_adapter,
        "list_windows",
        lambda: {"windows": [{"id": 1, "process_name": "chrome", "title": "Docs"}], "count": 1},
    )

    def fail_take_screenshot(*args, **kwargs):
        raise AssertionError("fast mode screenshot almamali")

    def fail_ocr(*args, **kwargs):
        raise AssertionError("fast mode OCR calistirmamali")

    monkeypatch.setattr(desktop_adapter, "take_screenshot", fail_take_screenshot)
    monkeypatch.setattr(desktop_adapter, "_extract_ocr_text", fail_ocr)

    result = desktop_adapter.read_screen(mode="fast")

    assert result["mode"] == "fast"
    assert result["active_window_guess"]["process_name"] == "chrome"
    assert result["screenshot"] is None
    assert result["ocr_available"] is False
    assert result["ui_text_count"] == 0


def test_read_screen_medium_takes_screenshot_but_skips_ocr(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop_adapter,
        "list_windows",
        lambda: {"windows": [{"id": 1, "process_name": "chrome", "title": "Docs"}], "count": 1},
    )
    monkeypatch.setattr(
        desktop_adapter,
        "take_screenshot",
        lambda save_name=None: {"tool": "take_screenshot", "path": "C:/tmp/test.png", "width": 100, "height": 100},
    )

    def fail_ocr(*args, **kwargs):
        raise AssertionError("medium mode OCR calistirmamali")

    monkeypatch.setattr(desktop_adapter, "_extract_ocr_text", fail_ocr)

    result = desktop_adapter.read_screen(mode="medium")

    assert result["mode"] == "medium"
    assert result["screenshot"]["path"] == "C:/tmp/test.png"
    assert result["ocr_available"] is False
    assert result["ui_text_count"] == 0
    assert "timing_ms" in result


def test_take_screenshot_reuses_recent_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(desktop_adapter, "BASE_DIR", tmp_path)
    call_count = {"value": 0}

    def fake_run_powershell(command: str, *, timeout: int = 30):
        call_count["value"] += 1
        screenshot_path = tmp_path / "data" / "screenshots" / "cached-test.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(b"fake")
        return subprocess.CompletedProcess(
            args=["powershell"],
            returncode=0,
            stdout=json.dumps({"path": str(screenshot_path), "width": 100, "height": 100}),
            stderr="",
        )

    monkeypatch.setattr(desktop_adapter, "_run_powershell", fake_run_powershell)

    first = desktop_adapter.take_screenshot(save_name="cached-test")
    second = desktop_adapter.take_screenshot(save_name="cached-test")

    assert first["cached"] is False
    assert second["cached"] is True
    assert call_count["value"] == 1
