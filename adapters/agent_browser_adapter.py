from __future__ import annotations

import atexit
import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_SCRIPT_PATH = BASE_DIR / "scripts" / "agent-browser-session.mjs"
PDF_LINK_EXTRACTOR_PATH = BASE_DIR / "scripts" / "pdf-link-extractor.mjs"
DEFAULT_AGENT_BROWSER_DIR = BASE_DIR / "data" / "agent-browser"


class AgentBrowserError(RuntimeError):
    """Raised when the agent browser runtime cannot complete a request."""


@dataclass(slots=True)
class AgentBrowserSessionResult:
    session_id: str
    title: str | None
    url: str | None
    page_count: int
    mode: str
    user_data_dir: str
    reused: bool = False
    opened: bool = False
    loaded: bool = False
    closed: bool = False


@dataclass(slots=True)
class PdfLink:
    index: int
    page_number: int
    url: str | None
    dest: str | list[Any] | None
    label: str | None
    contents: str | None
    title: str | None
    rect: list[float]


class _AgentBrowserWorker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def _start(self) -> None:
        if self._process and self._process.poll() is None:
            return
        self._process = subprocess.Popen(
            ["node", str(SESSION_SCRIPT_PATH), "--serve"],
            cwd=str(BASE_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    def _stop(self) -> None:
        process = self._process
        if not process:
            return
        if process.poll() is not None:
            self._process = None
            return
        try:
            self.send({"action": "shutdown"}, auto_start=False)
        except Exception:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        self._process = None

    def send(self, payload: dict[str, Any], *, auto_start: bool = True) -> dict[str, Any]:
        with self._lock:
            if auto_start:
                self._start()
            process = self._process
            if not process or process.poll() is not None or not process.stdin or not process.stdout:
                raise AgentBrowserError("Agent Browser worker kullanilabilir degil.")

            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()

            line = process.stdout.readline()
            if not line:
                raise AgentBrowserError("Agent Browser worker yanit vermedi.")

            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AgentBrowserError(f"Agent Browser worker gecersiz JSON dondurdu: {line!r}") from exc

            if not response.get("ok", False):
                message = response.get("error") or "Agent Browser istegi basarisiz oldu."
                code = response.get("code")
                if code:
                    message = f"{message} ({code})"
                raise AgentBrowserError(message)
            return response.get("result", {})


_WORKER = _AgentBrowserWorker()
atexit.register(_WORKER._stop)


def _normalize_user_data_dir(session_id: str, user_data_dir: str | None = None) -> str:
    if user_data_dir:
        return str(Path(user_data_dir).resolve())
    safe_session = session_id.strip() or "browser-main"
    return str((DEFAULT_AGENT_BROWSER_DIR / safe_session).resolve())


def _coerce_session_result(result: dict[str, Any]) -> AgentBrowserSessionResult:
    return AgentBrowserSessionResult(
        session_id=str(result.get("session_id") or "browser-main"),
        title=result.get("title"),
        url=result.get("url"),
        page_count=int(result.get("page_count") or 0),
        mode=str(result.get("mode") or "web"),
        user_data_dir=str(result.get("user_data_dir") or ""),
        reused=bool(result.get("reused", False)),
        opened=bool(result.get("opened", False)),
        loaded=bool(result.get("loaded", False)),
        closed=bool(result.get("closed", False)),
    )


def open_agent_browser_session(
    *,
    session_id: str = "browser-main",
    target_url: str | None = None,
    user_data_dir: str | None = None,
) -> AgentBrowserSessionResult:
    if target_url:
        target_url = target_url.strip()
        if not target_url.startswith(("http://", "https://", "file://", "about:", "chrome://")):
            target_url = "https://" + target_url

    result = _WORKER.send(
        {
            "action": "open_session",
            "sessionId": session_id,
            "targetUrl": target_url,
            "userDataDir": _normalize_user_data_dir(session_id, user_data_dir),
        }
    )
    return _coerce_session_result(result)


def navigate_agent_browser(
    url: str,
    *,
    session_id: str = "browser-main",
    user_data_dir: str | None = None,
) -> AgentBrowserSessionResult:
    url = url.strip()
    if not url.startswith(("http://", "https://", "file://", "about:", "chrome://")):
        url = "https://" + url

    result = _WORKER.send(
        {
            "action": "navigate",
            "sessionId": session_id,
            "url": url,
            "userDataDir": _normalize_user_data_dir(session_id, user_data_dir),
        }
    )
    return _coerce_session_result(result)


def open_document_in_agent_browser(
    file_path: str,
    *,
    session_id: str = "browser-main",
    user_data_dir: str | None = None,
) -> AgentBrowserSessionResult:
    resolved_path = str(Path(file_path).resolve())
    result = _WORKER.send(
        {
            "action": "open_document",
            "sessionId": session_id,
            "filePath": resolved_path,
            "userDataDir": _normalize_user_data_dir(session_id, user_data_dir),
        }
    )
    return _coerce_session_result(result)


def get_agent_browser_session_info(session_id: str = "browser-main") -> AgentBrowserSessionResult:
    result = _WORKER.send(
        {
            "action": "session_info",
            "sessionId": session_id,
        }
    )
    return _coerce_session_result(result)


def close_agent_browser_session(session_id: str = "browser-main") -> AgentBrowserSessionResult:
    result = _WORKER.send(
        {
            "action": "close_session",
            "sessionId": session_id,
        }
    )
    return _coerce_session_result(result)


def extract_pdf_links(
    pdf_path: str,
    *,
    max_pages: int | None = None,
    timeout_seconds: int = 45,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "pdfPath": str(Path(pdf_path).resolve()),
    }
    if max_pages is not None:
        payload["maxPages"] = max_pages

    completed = subprocess.run(
        ["node", str(PDF_LINK_EXTRACTOR_PATH), json.dumps(payload, ensure_ascii=False)],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "Bilinmeyen hata"
        raise AgentBrowserError(f"PDF link cikarimi basarisiz oldu: {stderr}")

    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AgentBrowserError("PDF link cikarici gecersiz JSON dondurdu.") from exc

    links = [
        PdfLink(
            index=int(item.get("index") or idx),
            page_number=int(item.get("page_number") or item.get("pageNumber") or 0),
            url=item.get("url"),
            dest=item.get("dest"),
            label=item.get("label"),
            contents=item.get("contents"),
            title=item.get("title"),
            rect=[float(value) for value in item.get("rect", [])],
        )
        for idx, item in enumerate(result.get("links", []))
    ]
    return {
        "pdf_path": str(Path(pdf_path).resolve()),
        "page_count": int(result.get("page_count") or 0),
        "link_count": len(links),
        "links": links,
    }
