from __future__ import annotations

import atexit
import base64
import json
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
PS_WORKER_SCRIPT_PATH = BASE_DIR / "scripts" / "ps_worker.ps1"
_WORKER_DONE_PREFIX = "__TA_DONE__"
_WORKER_ERROR_PREFIX = "__TA_ERROR__"
_SCREENSHOT_CACHE_TTL_SECONDS = 1.5
_SCREENSHOT_CACHE_LOCK = threading.Lock()
_SCREENSHOT_CACHE: dict[str, dict[str, object]] = {}


class _PowerShellWorker:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self.close()
        self._process = subprocess.Popen(
            [
                "powershell",
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PS_WORKER_SCRIPT_PATH),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                self._queue.put(line.rstrip("\r\n"))
        finally:
            self._queue.put(f"{_WORKER_DONE_PREFIX}:__worker_terminated__")

    def execute(self, command: str, *, timeout: int) -> subprocess.CompletedProcess[str]:
        with self._lock:
            self._ensure_started()
            process = self._process
            if process is None or process.stdin is None:
                raise RuntimeError("PowerShell worker baslatilamadi.")

            command_id = uuid.uuid4().hex
            done_marker = f"{_WORKER_DONE_PREFIX}:{command_id}"
            error_marker = f"{_WORKER_ERROR_PREFIX}:{command_id}"
            payload = json.dumps(
                {
                    "id": command_id,
                    "command_b64": base64.b64encode(command.encode("utf-8")).decode("ascii"),
                },
                ensure_ascii=True,
            )
            try:
                process.stdin.write(payload + "\n")
                process.stdin.flush()
            except Exception as exc:
                self.close()
                raise RuntimeError("PowerShell worker komutu alamadi.") from exc

            lines: list[str] = []
            error_mode = False
            error_message = ""

            until = time.time() + timeout
            while True:
                remaining = until - time.time()
                if remaining <= 0:
                    self.close()
                    raise RuntimeError("PowerShell worker zaman asimina ugradi.")
                try:
                    line = self._queue.get(timeout=remaining)
                except queue.Empty as exc:
                    self.close()
                    raise RuntimeError("PowerShell worker zaman asimina ugradi.") from exc

                if line == done_marker:
                    stdout = "\n".join(lines).strip()
                    if error_mode:
                        raise RuntimeError(error_message or stdout or "PowerShell komutu basarisiz.")
                    return subprocess.CompletedProcess(
                        args=["powershell", "-ExecutionPolicy", "Bypass", "-Command", command],
                        returncode=0,
                        stdout=stdout,
                        stderr="",
                    )
                if line == error_marker:
                    error_mode = True
                    continue
                if line.startswith(f"{_WORKER_DONE_PREFIX}:__worker_terminated__"):
                    self.close()
                    raise RuntimeError("PowerShell worker beklenmedik sekilde sonlandi.")
                if error_mode and not error_message and line:
                    error_message = line
                    continue
                lines.append(line)

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except Exception:
            pass
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


_PS_WORKER = _PowerShellWorker()
atexit.register(_PS_WORKER.close)


def _run_powershell(command: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return _PS_WORKER.execute(command, timeout=timeout)


def prewarm_desktop_runtime() -> dict[str, object]:
    started_at = time.perf_counter()
    command = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[pscustomobject]@{
    ready = $true
} | ConvertTo-Json -Depth 2
""".strip()
    completed = _run_powershell(command, timeout=20)
    payload = _load_json_output(completed.stdout) if completed.stdout.strip() else {"ready": True}
    return {
        "ready": bool(payload.get("ready")) if isinstance(payload, dict) else True,
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 1),
    }


def _escape_ps(value: str) -> str:
    return value.replace("'", "''")


def _load_json_output(stdout: str) -> dict[str, object] | list[object]:
    parsed = json.loads(stdout.strip())
    return parsed


def _run_local_python(command_args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [sys.executable, *command_args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return completed


def _extract_ocr_text(image_path: str, *, language_tag: str = "tr") -> dict[str, object]:
    script_path = BASE_DIR / "scripts" / "ocr_reader.py"
    completed = _run_local_python([str(script_path), image_path, language_tag], timeout=120)
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if not stdout:
        return {
            "ocr_available": False,
            "error": stderr or "OCR helper bos yanit dondu.",
        }

    try:
        payload = _load_json_output(stdout)
    except Exception as exc:
        return {
            "ocr_available": False,
            "error": f"OCR helper gecersiz JSON dondu: {exc}",
            "raw_output": stdout[:500],
        }

    if not isinstance(payload, dict):
        return {"ocr_available": False, "error": "OCR helper beklenmeyen veri formati dondu."}

    if completed.returncode != 0 and "error" not in payload:
        payload["error"] = stderr or "OCR helper basarisiz oldu."
        payload["ocr_available"] = False

    return payload


def _get_cached_screenshot(cache_key: str) -> dict[str, object] | None:
    with _SCREENSHOT_CACHE_LOCK:
        entry = _SCREENSHOT_CACHE.get(cache_key)
        if not entry:
            return None
        created_at = float(entry.get("created_at", 0.0) or 0.0)
        result = entry.get("result")
        path = str((result or {}).get("path", "")).strip() if isinstance(result, dict) else ""
        if time.time() - created_at > _SCREENSHOT_CACHE_TTL_SECONDS or not path or not Path(path).exists():
            _SCREENSHOT_CACHE.pop(cache_key, None)
            return None
        cached_result = dict(result)
        cached_result["cached"] = True
        return cached_result


def _store_cached_screenshot(cache_key: str, result: dict[str, object]) -> None:
    with _SCREENSHOT_CACHE_LOCK:
        _SCREENSHOT_CACHE[cache_key] = {
            "created_at": time.time(),
            "result": dict(result),
        }


def list_windows() -> dict[str, object]:
    command = r"""
$items = Get-Process |
    Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle } |
    Sort-Object ProcessName, MainWindowTitle |
    Select-Object Id, ProcessName, MainWindowTitle
$items | ConvertTo-Json -Depth 4
""".strip()
    completed = _run_powershell(command)
    stdout = completed.stdout.strip()
    if not stdout:
        return {"windows": [], "count": 0}

    parsed = _load_json_output(stdout)
    windows = parsed if isinstance(parsed, list) else [parsed]
    normalized = [
        {
            "id": item.get("Id"),
            "process_name": item.get("ProcessName"),
            "title": item.get("MainWindowTitle"),
        }
        for item in windows
        if isinstance(item, dict)
    ]
    return {"windows": normalized, "count": len(normalized)}


def focus_window(*, title_contains: str | None = None, process_name: str | None = None) -> dict[str, object]:
    title_filter = _escape_ps((title_contains or "").strip())
    process_filter = _escape_ps((process_name or "").strip())
    command = f"""
$ErrorActionPreference = 'Stop'
$titleFilter = '{title_filter}'
$processFilter = '{process_filter}'
$items = Get-Process | Where-Object {{
    $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -and
    (($titleFilter -eq '') -or $_.MainWindowTitle -like "*$titleFilter*") -and
    (($processFilter -eq '') -or $_.ProcessName -like "*$processFilter*")
}} | Select-Object -First 1
if (-not $items) {{ throw 'Hedef pencere bulunamadi.' }}
$def = @"
using System;
using System.Runtime.InteropServices;
public class FocusCore {{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}}
"@
Add-Type -TypeDefinition $def
[FocusCore]::ShowWindow($items.MainWindowHandle, 9) | Out-Null
[FocusCore]::SetForegroundWindow($items.MainWindowHandle) | Out-Null
[pscustomobject]@{{
    id = $items.Id
    process_name = $items.ProcessName
    title = $items.MainWindowTitle
    focused = $true
}} | ConvertTo-Json -Depth 4
""".strip()
    completed = _run_powershell(command)
    parsed = _load_json_output(completed.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError("Pencere odaklama yaniti gecersiz.")
    return parsed


def wait_for_window(
    *,
    title_contains: str | None = None,
    process_name: str | None = None,
    timeout_seconds: int = 20,
    poll_interval_ms: int = 500,
) -> dict[str, object]:
    title_filter = _escape_ps((title_contains or "").strip())
    process_filter = _escape_ps((process_name or "").strip())
    timeout_seconds = max(1, min(int(timeout_seconds), 120))
    poll_interval_ms = max(100, min(int(poll_interval_ms), 5000))
    command = f"""
$ErrorActionPreference = 'Stop'
$titleFilter = '{title_filter}'
$processFilter = '{process_filter}'
$deadline = (Get-Date).AddSeconds({timeout_seconds})
while ((Get-Date) -lt $deadline) {{
    $item = Get-Process | Where-Object {{
        $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -and
        (($titleFilter -eq '') -or $_.MainWindowTitle -like "*$titleFilter*") -and
        (($processFilter -eq '') -or $_.ProcessName -like "*$processFilter*")
    }} | Select-Object -First 1
    if ($item) {{
        [pscustomobject]@{{
            id = $item.Id
            process_name = $item.ProcessName
            title = $item.MainWindowTitle
            found = $true
        }} | ConvertTo-Json -Depth 4
        exit 0
    }}
    Start-Sleep -Milliseconds {poll_interval_ms}
}}
throw 'Beklenen pencere zamaninda bulunamadi.'
""".strip()
    completed = _run_powershell(command, timeout=timeout_seconds + 5)
    parsed = _load_json_output(completed.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError("Pencere bekleme yaniti gecersiz.")
    return parsed


def click_ui(
    *,
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    text: str | None = None,
    title_contains: str | None = None,
    process_name: str | None = None,
) -> dict[str, object]:
    normalized_button = button.strip().lower()
    if normalized_button not in {"left", "right"}:
        raise ValueError("click_ui sadece left veya right button destekler.")

    if x is not None and y is not None:
        down_up = "0x0002; 0x0004" if normalized_button == "left" else "0x0008; 0x0010"
        command = f"""
$def = @"
using System;
using System.Runtime.InteropServices;
public class MouseCore {{
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, IntPtr dwExtraInfo);
}}
"@
Add-Type -TypeDefinition $def
[MouseCore]::SetCursorPos({int(x)}, {int(y)}) | Out-Null
[MouseCore]::mouse_event({down_up.split(';')[0].strip()}, 0, 0, 0, [IntPtr]::Zero)
[MouseCore]::mouse_event({down_up.split(';')[1].strip()}, 0, 0, 0, [IntPtr]::Zero)
[pscustomobject]@{{
    mode = 'coordinates'
    x = {int(x)}
    y = {int(y)}
    button = '{normalized_button}'
    clicked = $true
}} | ConvertTo-Json -Depth 3
""".strip()
        completed = _run_powershell(command)
        parsed = _load_json_output(completed.stdout)
        if not isinstance(parsed, dict):
            raise RuntimeError("Koordinat tiklama yaniti gecersiz.")
        return parsed

    target_text = (text or "").strip()
    if not target_text:
        raise ValueError("click_ui icin ya x/y ya da text gerekli.")

    title_filter = _escape_ps((title_contains or "").strip())
    process_filter = _escape_ps((process_name or "").strip())
    text_filter = _escape_ps(target_text)
    down_up = "0x0002; 0x0004" if normalized_button == "left" else "0x0008; 0x0010"

    command = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
function Normalize-UiText([string]$value) {{
    if ([string]::IsNullOrWhiteSpace($value)) {{ return '' }}
    $clean = [regex]::Replace($value, '\p{{Cc}}+', ' ')
    return $clean.Trim()
}}
$def = @"
using System;
using System.Runtime.InteropServices;
public class MouseCore {{
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, IntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}}
"@
Add-Type -TypeDefinition $def
$titleFilter = '{title_filter}'
$processFilter = '{process_filter}'
$textFilter = '{text_filter}'
$window = Get-Process | Where-Object {{
    $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -and
    (($titleFilter -eq '') -or $_.MainWindowTitle -like "*$titleFilter*") -and
    (($processFilter -eq '') -or $_.ProcessName -like "*$processFilter*")
}} | Select-Object -First 1
if (-not $window) {{ throw 'Hedef pencere bulunamadi.' }}
[MouseCore]::ShowWindow($window.MainWindowHandle, 9) | Out-Null
[MouseCore]::SetForegroundWindow($window.MainWindowHandle) | Out-Null
$root = [System.Windows.Automation.AutomationElement]::FromHandle($window.MainWindowHandle)
if (-not $root) {{ throw 'UIAutomation kok pencere bulunamadi.' }}
$nodes = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$target = $null
foreach ($node in $nodes) {{
    try {{
        $name = Normalize-UiText $node.Current.Name
        if ($name -and $name -like "*$textFilter*") {{
            $target = $node
            break
        }}
    }} catch {{}}
}}
if (-not $target) {{ throw 'Istenen UI metni bulunamadi.' }}
$rect = $target.Current.BoundingRectangle
if ($rect.Width -le 0 -or $rect.Height -le 0) {{ throw 'Hedef UI elemaninin tiklanabilir alani yok.' }}
$clickX = [int]($rect.Left + ($rect.Width / 2))
$clickY = [int]($rect.Top + ($rect.Height / 2))
[MouseCore]::SetCursorPos($clickX, $clickY) | Out-Null
[MouseCore]::mouse_event({down_up.split(';')[0].strip()}, 0, 0, 0, [IntPtr]::Zero)
[MouseCore]::mouse_event({down_up.split(';')[1].strip()}, 0, 0, 0, [IntPtr]::Zero)
[pscustomobject]@{{
    mode = 'ui_automation_text'
    button = '{normalized_button}'
    x = $clickX
    y = $clickY
    matched_text = Normalize-UiText $target.Current.Name
    title = Normalize-UiText $window.MainWindowTitle
    process_name = Normalize-UiText $window.ProcessName
    clicked = $true
}} | ConvertTo-Json -Depth 4
""".strip()
    completed = _run_powershell(command, timeout=45)
    parsed = _load_json_output(completed.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError("UI metin tiklama yaniti gecersiz.")
    return parsed


def take_screenshot(*, save_name: str | None = None, use_cache: bool = True) -> dict[str, object]:
    screenshots_dir = BASE_DIR / "data" / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", (save_name or "screenshot").strip()).strip("-") or "screenshot"
    if not safe_name.lower().endswith(".png"):
        safe_name += ".png"
    cache_key = safe_name.lower()
    if use_cache:
        cached = _get_cached_screenshot(cache_key)
        if cached is not None:
            cached.setdefault("tool", "take_screenshot")
            cached.setdefault("timing_ms", 0.0)
            return cached
    screenshot_path = screenshots_dir / safe_name
    started_at = time.perf_counter()
    command = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bitmap.Size)
$bitmap.Save('{_escape_ps(str(screenshot_path))}', [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
[pscustomobject]@{{
    path = '{_escape_ps(str(screenshot_path))}'
    width = $bounds.Width
    height = $bounds.Height
}} | ConvertTo-Json -Depth 3
""".strip()
    completed = _run_powershell(command, timeout=120)
    parsed = _load_json_output(completed.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError("Ekran goruntusu yaniti gecersiz.")
    parsed["tool"] = "take_screenshot"
    parsed["cached"] = False
    parsed["timing_ms"] = round((time.perf_counter() - started_at) * 1000, 1)
    if use_cache:
        _store_cached_screenshot(cache_key, parsed)
    return parsed


def read_screen(*, save_name: str | None = None, mode: str | None = None) -> dict[str, object]:
    normalized_mode = str(mode or "medium").strip().lower() or "medium"
    if normalized_mode not in {"fast", "medium", "full"}:
        normalized_mode = "medium"

    started_at = time.perf_counter()
    timings: dict[str, float] = {}
    screenshot: dict[str, object] | None = None
    list_windows_started_at = time.perf_counter()
    windows = list_windows()
    timings["list_windows"] = round((time.perf_counter() - list_windows_started_at) * 1000, 1)
    if normalized_mode in {"medium", "full"}:
        screenshot_started_at = time.perf_counter()
        screenshot = take_screenshot(save_name=save_name or "read-screen")
        timings["take_screenshot"] = round((time.perf_counter() - screenshot_started_at) * 1000, 1)
    top_window = windows["windows"][0] if windows["windows"] else None
    title_filter = _escape_ps(str(top_window.get("title", "")) if isinstance(top_window, dict) else "")
    process_filter = _escape_ps(str(top_window.get("process_name", "")) if isinstance(top_window, dict) else "")

    ui_texts: list[dict[str, object]] = []
    extraction_note = "UIAutomation metinleri atlandi."
    if normalized_mode == "full" and top_window:
        ui_started_at = time.perf_counter()
        command = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
function Normalize-UiText([string]$value) {{
    if ([string]::IsNullOrWhiteSpace($value)) {{ return '' }}
    $clean = [regex]::Replace($value, '\p{{Cc}}+', ' ')
    return $clean.Trim()
}}
$titleFilter = '{title_filter}'
$processFilter = '{process_filter}'
$window = Get-Process | Where-Object {{
    $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -and
    (($titleFilter -eq '') -or $_.MainWindowTitle -eq $titleFilter) -and
    (($processFilter -eq '') -or $_.ProcessName -eq $processFilter)
}} | Select-Object -First 1
if (-not $window) {{ throw 'Aktif pencere bulunamadi.' }}
$root = [System.Windows.Automation.AutomationElement]::FromHandle($window.MainWindowHandle)
if (-not $root) {{ throw 'UIAutomation kok pencere bulunamadi.' }}
$nodes = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$results = @()
foreach ($node in $nodes) {{
    if ($results.Count -ge 80) {{ break }}
    try {{
        $name = Normalize-UiText $node.Current.Name
        if ([string]::IsNullOrWhiteSpace($name)) {{ continue }}
        $rect = $node.Current.BoundingRectangle
        $results += [pscustomobject]@{{
            text = $name
            automation_id = Normalize-UiText $node.Current.AutomationId
            control_type = Normalize-UiText $node.Current.ControlType.ProgrammaticName
            x = [int]$rect.Left
            y = [int]$rect.Top
            width = [int]$rect.Width
            height = [int]$rect.Height
        }}
    }} catch {{}}
}}
$results | ConvertTo-Json -Depth 5
""".strip()
        try:
            completed = _run_powershell(command, timeout=45)
            parsed = _load_json_output(completed.stdout) if completed.stdout.strip() else []
            if isinstance(parsed, list):
                ui_texts = [item for item in parsed if isinstance(item, dict)]
            elif isinstance(parsed, dict):
                ui_texts = [parsed]
        except Exception as exc:
            extraction_note = f"UIAutomation metinleri toplanamadi: {exc}"
        timings["ui_automation"] = round((time.perf_counter() - ui_started_at) * 1000, 1)
    elif normalized_mode == "full":
        extraction_note = "Gorunen pencere bulunamadigi icin UI metni toplanamadi."

    ocr_result: dict[str, object] = {"ocr_available": False, "error": "OCR atlandi."}
    if normalized_mode == "full":
        screenshot_path = str((screenshot or {}).get("path", "")).strip()
        ocr_started_at = time.perf_counter()
        ocr_result = _extract_ocr_text(screenshot_path) if screenshot_path else {
            "ocr_available": False,
            "error": "OCR icin ekran goruntusu yolu bulunamadi.",
        }
        timings["ocr"] = round((time.perf_counter() - ocr_started_at) * 1000, 1)
    ocr_available = bool(ocr_result.get("ocr_available"))

    note_parts = [extraction_note]
    if normalized_mode != "full":
        note_parts.append("OCR atlandi.")
    elif ocr_available:
        note_parts.append("Windows OCR metni toplandi.")
    else:
        note_parts.append(f"Windows OCR kullanilamadi: {ocr_result.get('error', 'bilinmeyen hata')}")

    return {
        "tool": "read_screen",
        "mode": normalized_mode,
        "active_window_guess": top_window,
        "visible_windows": windows["windows"][:10],
        "ui_texts": ui_texts[:80],
        "ui_text_count": len(ui_texts),
        "ocr_available": ocr_available,
        "ocr_language": ocr_result.get("language"),
        "ocr_text": str(ocr_result.get("text", "")).strip(),
        "ocr_lines": ocr_result.get("lines", [])[:120] if isinstance(ocr_result.get("lines"), list) else [],
        "ocr_line_count": int(ocr_result.get("line_count", 0) or 0),
        "ocr_error": ocr_result.get("error"),
        "screenshot": screenshot,
        "note": " ".join(part for part in note_parts if part),
        "timing_ms": {
            **timings,
            "total": round((time.perf_counter() - started_at) * 1000, 1),
        },
    }

def type_ui(
    text_to_type: str,
    *,
    text_filter: str | None = None,
    title_contains: str | None = None,
    process_name: str | None = None,
) -> dict[str, object]:
    """
    Belirtilen metni (varsa text_filter uzerine tiklayarak) hedefe yazar.
    """
    clicked_info = None
    if text_filter:
        clicked_info = click_ui(
            text=text_filter, 
            button="left", 
            title_contains=title_contains, 
            process_name=process_name
        )
    else:
        if title_contains or process_name:
            focus_window(title_contains=title_contains, process_name=process_name)

    powershell_text = _escape_ps(text_to_type)
    command = f"""
Add-Type -AssemblyName System.Windows.Forms
Start-Sleep -Milliseconds 250
[System.Windows.Forms.SendKeys]::SendWait('{powershell_text}')
[pscustomobject]@{{
    mode = 'type'
    success = $true
}} | ConvertTo-Json -Depth 3
"""
    completed = _run_powershell(command.strip(), timeout=30)
    parsed = _load_json_output(completed.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError("Yazi yazma yaniti gecersiz.")
    
    parsed["focused_element"] = clicked_info
    parsed["tool"] = "type_ui"
    return parsed

def verify_ui_state(
    expected_text: str | None = None,
    timeout_seconds: int = 5,
) -> dict[str, object]:
    """
    Aksiyon sonrasi hedef metnin ekranda belirmesini bekler veya mevcut ekran özetini dondurur.
    """
    import time
    start_time = time.time()
    found = False
    last_ui_texts = []
    
    while True:
        try:
            screen_data = read_screen(save_name="verify_ui_temp", mode="full")
            last_ui_texts = screen_data.get("ui_texts", [])
            
            if expected_text:
                expected_lower = expected_text.lower()
                for el in last_ui_texts:
                    el_name = str(el.get("text", "")).lower()
                    if expected_lower in el_name:
                        found = True
                        break
            else:
                return {
                    "tool": "verify_ui_state",
                    "status": "state_returned",
                    "ui_texts": last_ui_texts[:20]
                }
                
            if found:
                break
                
        except Exception:
            pass
            
        if time.time() - start_time > timeout_seconds:
            break
        time.sleep(1)

    return {
        "tool": "verify_ui_state",
        "status": "found" if found else "timeout",
        "expected_text": expected_text,
        "ui_texts_sample": last_ui_texts[:10]
    }
