from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _run_powershell(command: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "PowerShell komutu basarisiz.")
    return completed


def _escape_ps(value: str) -> str:
    return value.replace("'", "''")


def _load_json_output(stdout: str) -> dict[str, object] | list[object]:
    parsed = json.loads(stdout.strip())
    return parsed


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
        $name = $node.Current.Name
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
    matched_text = $target.Current.Name
    title = $window.MainWindowTitle
    process_name = $window.ProcessName
    clicked = $true
}} | ConvertTo-Json -Depth 4
""".strip()
    completed = _run_powershell(command, timeout=45)
    parsed = _load_json_output(completed.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError("UI metin tiklama yaniti gecersiz.")
    return parsed


def take_screenshot(*, save_name: str | None = None) -> dict[str, object]:
    screenshots_dir = BASE_DIR / "data" / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", (save_name or "screenshot").strip()).strip("-") or "screenshot"
    if not safe_name.lower().endswith(".png"):
        safe_name += ".png"
    screenshot_path = screenshots_dir / safe_name
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
    return parsed


def read_screen(*, save_name: str | None = None) -> dict[str, object]:
    screenshot = take_screenshot(save_name=save_name or "read-screen")
    windows = list_windows()
    top_window = windows["windows"][0] if windows["windows"] else None
    title_filter = _escape_ps(str(top_window.get("title", "")) if isinstance(top_window, dict) else "")
    process_filter = _escape_ps(str(top_window.get("process_name", "")) if isinstance(top_window, dict) else "")

    ui_texts: list[dict[str, object]] = []
    extraction_note = "UIAutomation metinleri toplandi."
    if top_window:
        command = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
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
        $name = $node.Current.Name
        if ([string]::IsNullOrWhiteSpace($name)) {{ continue }}
        $rect = $node.Current.BoundingRectangle
        $results += [pscustomobject]@{{
            text = $name
            automation_id = $node.Current.AutomationId
            control_type = $node.Current.ControlType.ProgrammaticName
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
    else:
        extraction_note = "Gorunen pencere bulunamadigi icin UI metni toplanamadi."

    return {
        "tool": "read_screen",
        "mode": "window_inventory_plus_ui_text_plus_screenshot",
        "active_window_guess": top_window,
        "visible_windows": windows["windows"][:10],
        "ui_texts": ui_texts[:80],
        "ui_text_count": len(ui_texts),
        "screenshot": screenshot,
        "note": extraction_note,
    }
