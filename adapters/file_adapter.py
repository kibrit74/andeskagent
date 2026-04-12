from __future__ import annotations

import os
import subprocess
import zipfile
import time
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
from typing import Iterable
import unicodedata

from core.config import load_settings


@dataclass(slots=True)
class FileSearchResult:
    path: str
    name: str
    size_bytes: int
    modified_at: float


class WhitelistFileAdapter:
    def __init__(self, allowed_folders: Iterable[str]):
        self.allowed_roots = [Path(folder).expanduser().resolve() for folder in allowed_folders]

    def _is_allowed(self, path: Path) -> bool:
        resolved = path.expanduser().resolve()
        return any(resolved == root or root in resolved.parents for root in self.allowed_roots)

    def search(
        self,
        query: str,
        *,
        folder_hint: str | None = None,
        extensions: Iterable[str] | None = None,
        limit: int = 25,
        max_seconds: float = 8.0,
    ) -> list[FileSearchResult]:
        query_lower = _normalize_text(query)
        extension_set = {ext.lower().lstrip(".") for ext in extensions or [] if ext}
        search_roots = self.allowed_roots
        query_tokens = [
            token
            for token in re.split(r"[^a-z0-9]+", query_lower)
            if token and (len(token) >= 3 or (len(token) >= 2 and any(ch.isdigit() for ch in token)))
        ]

        def _token_match(normalized_name: str) -> bool:
            if not query_tokens:
                return True
            matched = sum(1 for token in query_tokens if token in normalized_name)
            required = 1 if len(query_tokens) <= 2 else 2
            return matched >= required

        if folder_hint:
            hinted = Path(folder_hint).expanduser().resolve()
            if self._is_allowed(hinted):
                search_roots = [hinted]

        results: list[FileSearchResult] = []
        started_at = time.perf_counter()

        def _within_budget() -> bool:
            return (time.perf_counter() - started_at) <= max_seconds

        def _add_result(path: Path) -> None:
            try:
                stat = path.stat()
            except OSError:
                return
            results.append(
                FileSearchResult(
                    path=str(path),
                    name=path.name,
                    size_bytes=stat.st_size,
                    modified_at=stat.st_mtime,
                )
            )

        for root in search_roots:
            if not root.exists():
                continue
            if not _within_budget():
                break
            # Fast pass: root + one level deep.
            try:
                for path in root.iterdir():
                    if len(results) >= limit or not _within_budget():
                        return sorted(results, key=lambda item: (item.modified_at, item.path), reverse=True)
                    if path.is_file():
                        normalized_name = _normalize_text(path.name)
                        if query_lower and query_lower not in normalized_name and not _token_match(normalized_name):
                            continue
                        if extension_set and path.suffix.lower().lstrip(".") not in extension_set:
                            continue
                        _add_result(path)
                    elif path.is_dir():
                        for nested in path.iterdir():
                            if len(results) >= limit or not _within_budget():
                                return sorted(results, key=lambda item: (item.modified_at, item.path), reverse=True)
                            if not nested.is_file():
                                continue
                            normalized_name = _normalize_text(nested.name)
                            if query_lower and query_lower not in normalized_name and not _token_match(normalized_name):
                                continue
                            if extension_set and nested.suffix.lower().lstrip(".") not in extension_set:
                                continue
                            _add_result(nested)
            except OSError:
                pass

            if len(results) >= limit or not _within_budget():
                return sorted(results, key=lambda item: (item.modified_at, item.path), reverse=True)

            for path in root.rglob("*"):
                if len(results) >= limit:
                    return sorted(results, key=lambda item: (item.modified_at, item.path), reverse=True)
                if not _within_budget():
                    return sorted(results, key=lambda item: (item.modified_at, item.path), reverse=True)
                if not path.is_file():
                    continue
                normalized_name = _normalize_text(path.name)
                if query_lower and query_lower not in normalized_name and not _token_match(normalized_name):
                    continue
                if extension_set and path.suffix.lower().lstrip(".") not in extension_set:
                    continue
                _add_result(path)

        return sorted(results, key=lambda item: (item.modified_at, item.path), reverse=True)

    def latest(self, query: str, **kwargs) -> FileSearchResult | None:
        matches = self.search(query, **kwargs)
        return max(matches, key=lambda item: item.modified_at) if matches else None

    def largest(self, query: str, **kwargs) -> FileSearchResult | None:
        matches = self.search(query, **kwargs)
        return max(matches, key=lambda item: item.size_bytes) if matches else None

    def copy_file(self, source: str | Path, destination_dir: str | Path) -> FileSearchResult:
        source_path = Path(source).expanduser().resolve()
        destination_root = Path(destination_dir).expanduser().resolve()

        if not source_path.exists() or not source_path.is_file():
            raise ValueError(f"Source file not found: {source_path}")
        if not self._is_allowed(source_path):
            raise PermissionError(f"Source path is not allowed: {source_path}")
        if not self._is_allowed(destination_root):
            raise PermissionError(f"Destination path is not allowed: {destination_root}")

        destination_root.mkdir(parents=True, exist_ok=True)

        stem = source_path.stem
        suffix = source_path.suffix

        def _next_copy_name(counter: int) -> Path:
            label = " - Kopya" if counter == 1 else f" - Kopya ({counter})"
            return destination_root / f"{stem}{label}{suffix}"

        candidates: list[Path] = []
        first_candidate = destination_root / source_path.name
        if first_candidate.resolve() != source_path and not first_candidate.exists():
            candidates.append(first_candidate)
        candidates.extend(_next_copy_name(counter) for counter in range(1, 11))

        copied_path: Path | None = None
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                shutil.copy2(source_path, candidate)
                copied_path = candidate
                break
            except PermissionError as exc:
                last_error = exc
                continue

        if copied_path is None:
            if last_error is not None:
                raise last_error
            raise PermissionError("Kopya dosya olusturulamadi.")

        stat = copied_path.stat()
        return FileSearchResult(
            path=str(copied_path),
            name=copied_path.name,
            size_bytes=stat.st_size,
            modified_at=stat.st_mtime,
        )

    def move_file(self, source: str | Path, destination_dir: str | Path) -> FileSearchResult:
        source_path = Path(source).expanduser().resolve()
        destination_root = Path(destination_dir).expanduser().resolve()

        if not source_path.exists() or not source_path.is_file():
            raise ValueError(f"Source file not found: {source_path}")
        if not self._is_allowed(source_path):
            raise PermissionError(f"Source path is not allowed: {source_path}")
        if not self._is_allowed(destination_root):
            raise PermissionError(f"Destination path is not allowed: {destination_root}")

        destination_root.mkdir(parents=True, exist_ok=True)

        target = destination_root / source_path.name
        counter = 1
        while target.exists():
            target = destination_root / f"{source_path.stem} ({counter}){source_path.suffix}"
            counter += 1

        moved_path = Path(shutil.move(str(source_path), str(target))).resolve()
        stat = moved_path.stat()
        return FileSearchResult(
            path=str(moved_path),
            name=moved_path.name,
            size_bytes=stat.st_size,
            modified_at=stat.st_mtime,
        )

    def rename_file(self, source: str | Path, new_name: str) -> FileSearchResult:
        source_path = Path(source).expanduser().resolve()
        if not source_path.exists() or not source_path.is_file():
            raise ValueError(f"Source file not found: {source_path}")
        if not self._is_allowed(source_path):
            raise PermissionError(f"Source path is not allowed: {source_path}")

        normalized_name = (new_name or "").strip().strip(".")
        if not normalized_name:
            raise ValueError("Yeni dosya adi gerekli.")
        safe_name = "".join(char for char in normalized_name if char not in '<>:"/\\|?*').strip()
        if not safe_name:
            raise ValueError("Gecerli bir yeni dosya adi gerekli.")
        if "." not in safe_name and source_path.suffix:
            safe_name = f"{safe_name}{source_path.suffix}"

        target = source_path.with_name(safe_name)
        counter = 1
        while target.exists() and target != source_path:
            stem = Path(safe_name).stem
            suffix = Path(safe_name).suffix
            target = source_path.with_name(f"{stem} ({counter}){suffix}")
            counter += 1

        renamed_path = source_path.rename(target)
        stat = renamed_path.stat()
        return FileSearchResult(
            path=str(renamed_path),
            name=renamed_path.name,
            size_bytes=stat.st_size,
            modified_at=stat.st_mtime,
        )

    def delete_file(self, source: str | Path) -> dict[str, object]:
        source_path = Path(source).expanduser().resolve()
        if not source_path.exists() or not source_path.is_file():
            raise ValueError(f"Source file not found: {source_path}")
        if not self._is_allowed(source_path):
            raise PermissionError(f"Source path is not allowed: {source_path}")

        source_path.unlink()
        return {"path": str(source_path), "name": source_path.name, "deleted": True}


def build_default_roots() -> list[str]:
    home = Path.home()
    return [str(home / "Desktop"), str(home / "Documents"), str(home / "Downloads")]


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char)).strip()


def location_to_path(location: str) -> Path:
    folder_hint_map = {
        "desktop": Path.home() / "Desktop",
        "documents": Path.home() / "Documents",
        "downloads": Path.home() / "Downloads",
    }
    return folder_hint_map.get(location.lower(), Path.home() / "Desktop")


def search_files(
    query: str,
    location: str = "desktop",
    extension: str | None = None,
    *,
    allowed_folders: Iterable[str] | None = None,
) -> list[dict[str, object]]:
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    folder_hint = location_to_path(location)
    results = adapter.search(
        query,
        folder_hint=str(folder_hint) if folder_hint else None,
        extensions=[extension] if extension else None,
        max_seconds=8.0,
    )
    return [
        {
            "path": result.path,
            "name": result.name,
            "size_bytes": result.size_bytes,
            "modified_at": result.modified_at,
        }
        for result in results
    ]


def copy_file_to_location(
    file_path: str,
    destination_location: str = "desktop",
    *,
    allowed_folders: Iterable[str] | None = None,
) -> dict[str, object]:
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    copied = adapter.copy_file(file_path, location_to_path(destination_location))
    return {
        "path": copied.path,
        "name": copied.name,
        "size_bytes": copied.size_bytes,
        "modified_at": copied.modified_at,
    }


def move_file_to_location(
    file_path: str,
    destination_location: str = "desktop",
    *,
    allowed_folders: Iterable[str] | None = None,
) -> dict[str, object]:
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    moved = adapter.move_file(file_path, location_to_path(destination_location))
    return {
        "path": moved.path,
        "name": moved.name,
        "size_bytes": moved.size_bytes,
        "modified_at": moved.modified_at,
    }


def rename_file_in_place(
    file_path: str,
    new_name: str,
    *,
    allowed_folders: Iterable[str] | None = None,
) -> dict[str, object]:
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    renamed = adapter.rename_file(file_path, new_name)
    return {
        "path": renamed.path,
        "name": renamed.name,
        "size_bytes": renamed.size_bytes,
        "modified_at": renamed.modified_at,
    }


def delete_file_in_place(
    file_path: str,
    *,
    allowed_folders: Iterable[str] | None = None,
) -> dict[str, object]:
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    return adapter.delete_file(file_path)


def create_folder_in_location(
    folder_name: str,
    destination_location: str = "desktop",
    *,
    allowed_folders: Iterable[str] | None = None,
) -> dict[str, object]:
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    destination_root = location_to_path(destination_location).expanduser().resolve()

    if not adapter._is_allowed(destination_root):
        raise PermissionError(f"Destination path is not allowed: {destination_root}")

    normalized_name = (folder_name or "").strip().strip(".")
    if not normalized_name:
        normalized_name = "Yeni Klasor"

    safe_name = "".join(char for char in normalized_name if char not in '<>:"/\\|?*').strip()
    if not safe_name:
        safe_name = "Yeni Klasor"

    target = destination_root / safe_name
    counter = 1
    while target.exists():
        counter += 1
        target = destination_root / f"{safe_name} ({counter})"

    target.mkdir(parents=True, exist_ok=False)
    return {
        "path": str(target),
        "name": target.name,
        "location": destination_location,
    }


def create_text_file_in_directory(
    directory_path: str,
    file_name: str = "Yeni Metin Belgesi.txt",
    *,
    allowed_folders: Iterable[str] | None = None,
) -> dict[str, object]:
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    target_dir = Path(directory_path).expanduser().resolve()

    if not target_dir.exists() or not target_dir.is_dir():
        raise ValueError(f"Hedef klasor bulunamadi: {target_dir}")
    if not adapter._is_allowed(target_dir):
        raise PermissionError(f"Destination path is not allowed: {target_dir}")

    normalized_name = (file_name or "").strip().strip(".")
    if not normalized_name:
        normalized_name = "Yeni Metin Belgesi.txt"
    if not normalized_name.lower().endswith(".txt"):
        normalized_name += ".txt"

    safe_name = "".join(char for char in normalized_name if char not in '<>:"/\\|?*').strip()
    if not safe_name:
        safe_name = "Yeni Metin Belgesi.txt"

    target = target_dir / safe_name
    counter = 1
    while target.exists():
        stem = Path(safe_name).stem
        target = target_dir / f"{stem} ({counter}).txt"
        counter += 1

    target.write_text("", encoding="utf-8")
    return {
        "path": str(target),
        "name": target.name,
        "directory": str(target_dir),
    }


def find_file_in_directory(
    directory_path: str,
    file_query: str,
    *,
    extension: str | None = None,
    allowed_folders: Iterable[str] | None = None,
) -> dict[str, object] | None:
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    target_dir = Path(directory_path).expanduser().resolve()

    if not target_dir.exists() or not target_dir.is_dir():
        return None
    if not adapter._is_allowed(target_dir):
        raise PermissionError(f"Destination path is not allowed: {target_dir}")

    query_normalized = _normalize_text(file_query)
    extension_normalized = extension.lower().lstrip(".") if extension else None

    for item in sorted(target_dir.iterdir(), key=lambda path: path.name.lower()):
        if not item.is_file():
            continue
        if extension_normalized and item.suffix.lower().lstrip(".") != extension_normalized:
            continue
        if query_normalized and query_normalized not in _normalize_text(item.stem) and query_normalized not in _normalize_text(item.name):
            continue
        stat = item.stat()
        return {
            "path": str(item),
            "name": item.name,
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
        }
    return None


def write_text_to_file(
    file_path: str,
    content: str,
    *,
    append: bool = False,
    allowed_folders: Iterable[str] | None = None,
) -> dict[str, object]:
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    target_file = Path(file_path).expanduser().resolve()

    if not target_file.exists() or not target_file.is_file():
        raise ValueError(f"Hedef dosya bulunamadi: {target_file}")
    if not adapter._is_allowed(target_file):
        raise PermissionError(f"Destination path is not allowed: {target_file}")

    existing = target_file.read_text(encoding="utf-8", errors="ignore") if append else ""
    target_file.write_text(f"{existing}{content}", encoding="utf-8")
    stat = target_file.stat()
    return {
        "path": str(target_file),
        "name": target_file.name,
        "size_bytes": stat.st_size,
        "modified_at": stat.st_mtime,
        "written_text": content,
        "append": append,
    }


def copy_files_to_path(
    file_paths: list[str],
    destination_path: str,
    *,
    allowed_folders: Iterable[str] | None = None,
) -> list[dict[str, object]]:
    """Birden fazla dosyayi belirtilen mutlak klasor yoluna kopyalar."""
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    dest = Path(destination_path).expanduser().resolve()

    if not dest.exists() or not dest.is_dir():
        raise ValueError(f"Hedef klasor bulunamadi: {dest}")
    if not adapter._is_allowed(dest):
        raise PermissionError(f"Hedef klasor izinli degil: {dest}")

    results: list[dict[str, object]] = []
    for fp in file_paths:
        source = Path(fp).expanduser().resolve()
        if not source.exists() or not source.is_file():
            continue
        if not adapter._is_allowed(source):
            continue
        copied = adapter.copy_file(str(source), str(dest))
        results.append({
            "path": copied.path,
            "name": copied.name,
            "size_bytes": copied.size_bytes,
            "modified_at": copied.modified_at,
        })
    return results


def move_files_to_path(
    file_paths: list[str],
    destination_path: str,
    *,
    allowed_folders: Iterable[str] | None = None,
) -> list[dict[str, object]]:
    """Birden fazla dosyayi belirtilen mutlak klasor yoluna tasir."""
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    dest = Path(destination_path).expanduser().resolve()

    if not dest.exists() or not dest.is_dir():
        raise ValueError(f"Hedef klasor bulunamadi: {dest}")
    if not adapter._is_allowed(dest):
        raise PermissionError(f"Hedef klasor izinli degil: {dest}")

    results: list[dict[str, object]] = []
    for fp in file_paths:
        source = Path(fp).expanduser().resolve()
        if not source.exists() or not source.is_file():
            continue
        if not adapter._is_allowed(source):
            continue
        moved = adapter.move_file(str(source), str(dest))
        results.append({
            "path": moved.path,
            "name": moved.name,
            "size_bytes": moved.size_bytes,
            "modified_at": moved.modified_at,
        })
    return results


def zip_directory(
    directory_path: str,
    output_name: str | None = None,
    *,
    allowed_folders: Iterable[str] | None = None,
) -> dict[str, object]:
    """Bir klasorun icerigini zip dosyasi olarak arsivler."""
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    source_dir = Path(directory_path).expanduser().resolve()

    if not source_dir.exists() or not source_dir.is_dir():
        raise ValueError(f"Kaynak klasor bulunamadi: {source_dir}")
    if not adapter._is_allowed(source_dir):
        raise PermissionError(f"Kaynak klasor izinli degil: {source_dir}")

    safe_name = (output_name or source_dir.name).strip()
    safe_name = "".join(c for c in safe_name if c not in '<>:"/\\|?*').strip() or "arsiv"
    if not safe_name.lower().endswith(".zip"):
        safe_name += ".zip"

    zip_path = source_dir.parent / safe_name
    counter = 1
    while zip_path.exists():
        stem = Path(safe_name).stem
        zip_path = source_dir.parent / f"{stem} ({counter}).zip"
        counter += 1

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(source_dir.rglob("*")):
            if item.is_file():
                zf.write(str(item), item.relative_to(source_dir))

    stat = zip_path.stat()
    return {
        "zip_path": str(zip_path),
        "name": zip_path.name,
        "size_bytes": stat.st_size,
        "file_count": sum(1 for f in source_dir.rglob("*") if f.is_file()),
        "source_directory": str(source_dir),
    }


def filter_files_by_date(
    files: list[dict[str, object]],
    *,
    month: int | None = None,
    year: int | None = None,
) -> list[dict[str, object]]:
    """Dosya listesini modified_at tarihine gore filtreler."""
    filtered: list[dict[str, object]] = []
    current_year = datetime.now().year

    for item in files:
        modified_at = item.get("modified_at")
        if modified_at is None:
            continue
        try:
            dt = datetime.fromtimestamp(float(modified_at))
        except (ValueError, OSError, OverflowError):
            continue

        target_year = year or current_year
        if dt.year != target_year:
            continue
        if month is not None and dt.month != month:
            continue
        filtered.append(item)

    return filtered


def open_file_path(
    file_path: str,
    *,
    allowed_folders: Iterable[str] | None = None,
) -> dict[str, object]:
    roots = list(allowed_folders or load_settings().allowed_folders or build_default_roots())
    adapter = WhitelistFileAdapter(roots)
    target_file = Path(file_path).expanduser().resolve()

    if not target_file.exists() or not target_file.is_file():
        raise ValueError(f"Hedef dosya bulunamadi: {target_file}")
    if not adapter._is_allowed(target_file):
        raise PermissionError(f"Destination path is not allowed: {target_file}")

    try:
        os.startfile(str(target_file))  # type: ignore[attr-defined]
    except AttributeError:
        escaped_target = str(target_file).replace("'", "''")
        completed = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", f"Start-Process -FilePath '{escaped_target}'"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Dosya acilamadi.")

    stat = target_file.stat()
    return {
        "path": str(target_file),
        "name": target_file.name,
        "size_bytes": stat.st_size,
        "modified_at": stat.st_mtime,
        "opened": True,
        "title_hint": target_file.stem[:80],
    }
