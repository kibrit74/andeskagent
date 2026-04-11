from __future__ import annotations

from dataclasses import dataclass
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
    ) -> list[FileSearchResult]:
        query_lower = _normalize_text(query)
        extension_set = {ext.lower().lstrip(".") for ext in extensions or [] if ext}
        search_roots = self.allowed_roots

        if folder_hint:
            hinted = Path(folder_hint).expanduser().resolve()
            if self._is_allowed(hinted):
                search_roots = [hinted]

        results: list[FileSearchResult] = []
        for root in search_roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if len(results) >= limit:
                    return sorted(results, key=lambda item: (item.modified_at, item.path), reverse=True)
                if not path.is_file():
                    continue
                if query_lower and query_lower not in _normalize_text(path.name):
                    continue
                if extension_set and path.suffix.lower().lstrip(".") not in extension_set:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                results.append(
                    FileSearchResult(
                        path=str(path),
                        name=path.name,
                        size_bytes=stat.st_size,
                        modified_at=stat.st_mtime,
                    )
                )

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
