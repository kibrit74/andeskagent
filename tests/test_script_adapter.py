from __future__ import annotations

import pytest

from adapters import script_adapter


def test_resolve_refs_supports_nested_structures() -> None:
    context = {
        "last_items": [{"path": "C:/tmp/a.txt"}],
        "known_paths": {"desktop": "C:/Users/test/Desktop"},
    }

    resolved = script_adapter._resolve_refs(
        {
            "file_paths": "$ref:last_items",
            "payload": {
                "target": "$ref:known_paths.desktop",
                "files": ["$ref:last_items.0.path"],
            },
        },
        context,
    )

    assert resolved == {
        "file_paths": [{"path": "C:/tmp/a.txt"}],
        "payload": {
            "target": "C:/Users/test/Desktop",
            "files": ["C:/tmp/a.txt"],
        },
    }


def test_resolve_refs_raises_for_missing_key() -> None:
    with pytest.raises(KeyError):
        script_adapter._resolve_refs({"file_path": "$ref:last_zip_path"}, {})


def test_execute_tool_chain_reports_failed_step(monkeypatch, tmp_path: Path) -> None:
    created_dir = tmp_path / "Arsiv"
    created_dir.mkdir()

    def fake_execute(step: dict[str, object]) -> dict[str, object]:
        tool = str(step["tool"])
        if tool == "create_folder":
            return {"tool": tool, "created_folder": {"path": str(created_dir)}}
        if tool == "zip_folder":
            raise ValueError("Kaynak klasor bulunamadi.")
        raise AssertionError("beklenmeyen tool")

    monkeypatch.setattr(script_adapter, "_execute_tool_step", fake_execute)
    monkeypatch.setattr(
        script_adapter,
        "location_to_path",
        lambda name: Path({
            "desktop": str(tmp_path),
            "documents": str(tmp_path / "Documents"),
            "downloads": str(tmp_path / "Downloads"),
        }[name]),
    )

    result = script_adapter._execute_tool_chain(
        [
            {"tool": "create_folder", "args": {"folder_name": "Arsiv"}},
            {"tool": "zip_folder", "args": {"folder_path": "$ref:last_folder_path"}},
        ],
        summary="demo",
    )

    assert result["success"] is False
    assert result["step_count"] == 2
    assert result["failed_step"] == {
        "tool": "zip_folder",
        "status": "error",
        "error": "Kaynak klasor bulunamadi.",
        "step_index": 1,
        "args": {"folder_path": "$ref:last_folder_path"},
    }
    assert "known_paths" in result["context_keys"]


def test_extract_excel_cells_parses_header_columns() -> None:
    cells = script_adapter._extract_excel_cells(
        "Excel calisma kitabi ac ve A sutununa Baslik olarak D.T B sutun basligina Sozlesme Hesabi yazip kaydet"
    )

    assert cells == [
        {"cell": "A1", "value": "D.T"},
        {"cell": "B1", "value": "Sozlesme Hesabi"},
    ]


def test_execute_tool_chain_blocks_on_failed_verification(monkeypatch) -> None:
    def fake_execute(step: dict[str, object]) -> dict[str, object]:
        if step["tool"] == "search_files":
            return {"tool": "search_files", "items": [], "count": 0, "resolved_location": "desktop"}
        raise AssertionError("sonraki adima gecilmemeliydi")

    monkeypatch.setattr(script_adapter, "_execute_tool_step", fake_execute)
    monkeypatch.setattr(
        script_adapter,
        "location_to_path",
        lambda name: Path({
            "desktop": "C:/Users/test/Desktop",
            "documents": "C:/Users/test/Documents",
            "downloads": "C:/Users/test/Downloads",
        }[name]),
    )

    result = script_adapter._execute_tool_chain(
        [
            {"tool": "search_files", "args": {"query": "rapor"}},
            {"tool": "zip_folder", "args": {"folder_path": "$ref:last_folder_path"}},
        ],
        summary="demo",
    )

    assert result["success"] is False
    assert result["verified_step_count"] == 0
    assert result["blocked_step"] == {
        "tool": "search_files",
        "status": "blocked",
        "verification": "Eslesen dosya bulunamadi.",
        "step_index": 0,
        "args": {"query": "rapor"},
    }
    assert result["steps"][0]["status"] == "blocked"
    assert result["steps"][0]["verified"] is False
