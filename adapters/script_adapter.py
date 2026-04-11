from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, cast

from adapters.file_adapter import copy_file_to_location, search_files
from adapters.gemini_adapter import generate_powershell_script_with_gemini
from adapters.mail_adapter import send_email_with_attachment
from adapters.system_adapter import get_system_status
from core.config import load_settings

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_PATH = BASE_DIR / "scripts" / "manifest.json"
FALLBACK_LOCATIONS = ("desktop", "documents", "downloads")


@dataclass(slots=True)
class ScriptExecutionResult:
    script: str
    stdout: str
    stderr: str
    returncode: int


class ScriptAdapter:
    def __init__(self, *, manifest_path: Path | None = None, allowed_scripts: Iterable[str] | None = None):
        self.manifest_path = manifest_path or DEFAULT_MANIFEST_PATH
        self.allowed_scripts = {name for name in allowed_scripts or []}

    def _manifest(self) -> dict[str, Any]:
        with self.manifest_path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)

    def list_scripts(self) -> list[dict[str, str]]:
        return list(self._manifest().get("scripts", []))

    def run(self, script_name: str) -> ScriptExecutionResult:
        if self.allowed_scripts and script_name not in self.allowed_scripts:
            raise ValueError("Script whitelist disinda.")

        selected = next((item for item in self.list_scripts() if item.get("name") == script_name), None)
        if not selected:
            raise ValueError("Script manifest icinde bulunamadi.")

        command_path = BASE_DIR / selected["path"]
        suffix = command_path.suffix.lower()
        if suffix == ".ps1":
            command = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(command_path)]
        elif suffix in {".bat", ".cmd"}:
            command = ["cmd.exe", "/c", str(command_path)]
        else:
            raise ValueError(f"Desteklenmeyen script turu: {command_path.name}")

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Script zaman asimina ugradi (5 dakika): {script_name}") from exc
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Script basarisiz.")

        return ScriptExecutionResult(
            script=script_name,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
            returncode=completed.returncode,
        )


def _build_generation_prompt(
    instruction: str,
    *,
    allowed_folders: Iterable[str],
    forbidden_actions: Iterable[str],
) -> str:
    return f"""
Sen Windows otomasyon arac planlayicisisin.
Kullanicinin istegini yerine getirecek tek bir JSON nesnesi don.

Kurallar:
- Markdown kullanma.
- Sadece gecerli JSON don.
- JSON alanlari: summary, steps
- steps bir dizi olsun.
- Her step bir object olsun ve alanlari: tool, args
- Desteklenen tool degerleri:
  - get_system_status
  - search_files
  - copy_file
  - send_file
  - list_scripts
  - run_whitelisted_script
    - open_application
  - take_screenshot
  - send_keys
  - run_powershell
- Kullanici istegini script yazarak cozmeye kosma; once uygun tool sec.
- Kullanici sistem bilgisi istiyorsa get_system_status kullan.
- Kullanici dosya ariyorsa search_files kullan.
- Kullanici dosya kopyalamak istiyorsa copy_file kullan.
- Kullanici dosya gondermek istiyorsa send_file kullan.
- Kullanici script listesini istiyorsa list_scripts kullan.
- Kullanici whitelist script calistirmak istiyorsa run_whitelisted_script kullan.
- Kullanici bir uygulama acmak istiyorsa open_application kullan.
- Kullanici ekran resmi istiyorsa take_screenshot kullan.
- Kullanici arayuzde yazi yazmak (type) veya Enter'a basmak istiyorsa send_keys kullan.
- Kullanici hem acma hem yazi yazma istiyorsa iki step don: once open_application sonra send_keys.
- Eger kullanici mantiksel kontroller (bul, bulamazsan bildir, ekle), sistem veya donanim islemleri istiyorsa MUTLAKA run_powershell kullan ve dinamik powershell scripti uret.
- Diger araclar sadece basit/statik ihtiyaclar veya mevcut scriptler icin kullanilmalidir.
- search_files args:
  - query
  - location: desktop, documents, downloads
  - extension: opsiyonel, noktasiz
- copy_file args:
  - query
  - location
  - extension
  - destination_location: desktop, documents, downloads
- send_file args:
  - query
  - location
  - extension
  - recipient
- get_system_status args bos olabilir.
- list_scripts args bos olabilir.
- run_whitelisted_script args:
  - script_name
- open_application args:
  - app_name: chrome, outlook, excel, word, notepad, calculator, paint, explorer gibi kisa bir ad veya direkt istenen uygulamanin kendisi
  - target: opsiyonel URL veya dosya yolu
- take_screenshot args:
  - save_name: opsiyonel png dosya adi
- send_keys args:
  - keys: Gonderilecek yazi metni
  - press_enter: true veya false. Eger islem sonunda onaylamak, gondermek veya mesaj atmak icin Enter'a basilmasi gerekiyorsa KESINLIKLE true don.
- run_powershell args:
  - script: tek basina calisabilir PowerShell script
- Uygulama ici ileri otomasyonlar icin, ornegin Outlook COM ile mail olusturma/gonderme gibi durumlarda run_powershell kullan.
- Bir istek belirli bir Windows uygulamasi icinde alan doldurma, mail gonderme, pencere kontrolu veya COM otomasyonu gerektiriyorsa run_powershell tercih et.
- Silme, registry degistirme, network ayari degistirme, formatlama, yeniden baslatma yapma.
- Sadece su klasorlerde dosya islemi yap: {", ".join(allowed_folders)}
- Asla su yasakli aksiyonlari yapma: {", ".join(forbidden_actions)}
- Mumkunse var olan dosyayi koruyup kopya/olusturma mantigi kullan.

Kullanici istegi:
{instruction}
""".strip()


def _assert_generated_script_safe(script: str) -> None:
    blocked_patterns = (
        r"\bRemove-Item\b",
        r"\bdel\b",
        r"\bFormat-\w+\b",
        r"\bSet-ItemProperty\b",
        r"\breg(\.exe)?\s+add\b",
        r"\breg(\.exe)?\s+delete\b",
        r"\bnetsh\b",
        r"\bNew-NetIPAddress\b",
        r"\bSet-NetIPAddress\b",
        r"\bRestart-Computer\b",
        r"\bStop-Computer\b",
        r"\bshutdown\b",
        r"\btaskkill\b",
    )
    for pattern in blocked_patterns:
        if re.search(pattern, script, flags=re.IGNORECASE):
            raise ValueError(f"Generated script blocked by safety rule: {pattern}")


def _run_powershell_script(script: str, *, summary: str) -> dict[str, object]:
    _assert_generated_script_safe(script)

    generated_dir = BASE_DIR / "data" / "generated-scripts"
    generated_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".ps1",
        prefix="generated-",
        dir=generated_dir,
        delete=False,
    ) as handle:
        handle.write("$ErrorActionPreference = 'Stop'\n")
        handle.write("Set-StrictMode -Version Latest\n")
        handle.write(script)
        script_path = Path(handle.name)

    out_fd, out_path = tempfile.mkstemp(suffix=".out")
    err_fd, err_path = tempfile.mkstemp(suffix=".err")
    try:
        with os.fdopen(out_fd, "w", encoding="utf-8") as out_f, os.fdopen(err_fd, "w", encoding="utf-8") as err_f:
            try:
                completed = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
                    stdout=out_f,
                    stderr=err_f,
                    timeout=120,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                ret_code = completed.returncode
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Generated script timed out after {int(exc.timeout or 120)} seconds."
                ) from exc
        with open(out_path, "r", encoding="utf-8", errors="replace") as f:
            stdout_text = f.read().strip()
        with open(err_path, "r", encoding="utf-8", errors="replace") as f:
            stderr_text = f.read().strip()
    finally:
        try: os.remove(out_path)
        except Exception: pass
        try: os.remove(err_path)
        except Exception: pass

    if ret_code != 0 or stderr_text:
        raise RuntimeError(stderr_text or stdout_text or "Generated script failed.")

    return {
        "summary": summary or "Generated script executed.",
        "tool": "run_powershell",
        "script_path": str(script_path),
        "stdout": stdout_text,
        "stderr": stderr_text,
        "returncode": ret_code,
        "script": script,
    }


def _resolve_application_target(app_name: str) -> str:
    app_map = {
        "chrome": "chrome",
        "google chrome": "chrome",
        "outlook": "outlook",
        "excel": "excel",
        "word": "winword",
        "notepad": "notepad",
        "calculator": "calc",
        "calc": "calc",
        "paint": "mspaint",
        "explorer": "explorer",
        "dosya gezgini": "explorer",
    }
    normalized = app_name.strip().lower()
    return app_map.get(normalized, normalized)


def _resolve_executable_candidates(app_name: str) -> list[str]:
    normalized = app_name.strip().lower()
    local_app_data = Path.home() / "AppData" / "Local"
    program_files = Path("C:/Program Files")
    program_files_x86 = Path("C:/Program Files (x86)")

    if normalized in {"chrome", "google chrome"}:
        return [
            str(program_files / "Google/Chrome/Application/chrome.exe"),
            str(program_files_x86 / "Google/Chrome/Application/chrome.exe"),
            str(local_app_data / "Google/Chrome/Application/chrome.exe"),
            "chrome",
            "msedge",
        ]
    if normalized in {"outlook"}:
        return ["outlook", "olk", "msedge"]
    if normalized in {"excel"}:
        return ["excel", "msedge"]
    if normalized in {"word"}:
        return ["winword", "msedge"]
    resolved = _resolve_application_target(app_name)
    candidates = []
    if resolved not in candidates:
        candidates.append(resolved)
    if f"{resolved}.exe" not in candidates:
        candidates.append(f"{resolved}.exe")
    if app_name not in candidates:
        candidates.append(app_name)
    return candidates


def _open_application(*, app_name: str, target: str | None = None) -> dict[str, object]:
    errors: list[str] = []
    escaped_target = (target or "about:blank").replace("'", "''")
    for executable in _resolve_executable_candidates(app_name):
        argument_list = ""
        normalized_executable = executable.lower()
        if "chrome" in normalized_executable or "msedge" in normalized_executable:
            argument_list = f" -ArgumentList '--new-window','--no-first-run','{escaped_target}'"
        elif target:
            argument_list = f" -ArgumentList '{escaped_target}'"

        proc_name = Path(executable).stem.replace("'", "''")
        ps_command = f"""
$ErrorActionPreference = 'SilentlyContinue'
$proc = Get-Process -Name '{proc_name}' | Where-Object {{ $_.MainWindowHandle -ne 0 }} | Select-Object -First 1
if ($proc) {{
    $def = @"
    using System;
    using System.Runtime.InteropServices;
    public class FocusCore {{
        [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    }}
"@
    Add-Type -TypeDefinition $def
    [FocusCore]::ShowWindow($proc.MainWindowHandle, 9)
    [FocusCore]::SetForegroundWindow($proc.MainWindowHandle)
}} else {{
    Start-Process -FilePath '{executable}'{argument_list}
}}
"""
        completed = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode == 0:
            return {
                "tool": "open_application",
                "app_name": app_name,
                "target": target,
                "opened_with": executable,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "returncode": completed.returncode,
            }
        errors.append(completed.stderr.strip() or completed.stdout.strip() or executable)

    raise RuntimeError(f"Uygulama acilamadi: {app_name}. Denenenler: {errors}")


def _take_screenshot(*, save_name: str | None = None) -> dict[str, object]:
    screenshots_dir = BASE_DIR / "data" / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", (save_name or "screenshot").strip()).strip("-") or "screenshot"
    if not safe_name.lower().endswith(".png"):
        safe_name += ".png"
    screenshot_path = screenshots_dir / safe_name
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bitmap.Size)
$bitmap.Save('{str(screenshot_path).replace("'", "''")}', [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
Write-Output '{str(screenshot_path).replace("'", "''")}'
""".strip()
    completed = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Ekran resmi alinamadi.")
    return {
        "tool": "take_screenshot",
        "path": str(screenshot_path),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "returncode": completed.returncode,
    }


def _send_keys(*, keys: str, press_enter: bool = False) -> dict[str, object]:
    # Eğer Gemini \n gönderdiyse onu sendkeys enter formatına çevir
    processed_keys = keys.replace("\n", "{ENTER}")
    
    if press_enter and not processed_keys.endswith("{ENTER}") and not processed_keys.endswith("~"):
        processed_keys += "{ENTER}"

    # SendKeys için tek tırnakları powershell formatına kaçmalıyız
    escaped_keys = processed_keys.replace("'", "''")
    
    ps_cmd = f"Add-Type -AssemblyName System.Windows.Forms; Start-Sleep -Seconds 2; [System.Windows.Forms.SendKeys]::SendWait('{escaped_keys}')"
    try:
        completed = subprocess.run(
           ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Klavye gonderimi zaman asimina ugradi.") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"Klavye metni gonderilemedi: {completed.stderr}")
    return {"tool": "send_keys", "keys": keys}


def _execute_tool_step(step: dict[str, Any]) -> dict[str, object]:
    tool = str(step.get("tool", "")).strip()
    args = cast(dict[str, Any], step.get("args") or {})
    settings = load_settings()

    def _search_with_fallback(query: str, location: str, extension: str | None) -> tuple[list[dict[str, object]], str]:
        preferred = (location or "desktop").strip() or "desktop"
        ordered_locations: list[str] = [preferred]
        ordered_locations.extend(item for item in FALLBACK_LOCATIONS if item != preferred)
        for candidate_location in ordered_locations:
            items = search_files(
                query=query,
                location=candidate_location,
                extension=extension,
                allowed_folders=settings.allowed_folders,
            )
            if items:
                return items, candidate_location
        return [], preferred

    if tool == "get_system_status":
        return {"tool": "get_system_status", "result": get_system_status()}
    if tool == "search_files":
        items, resolved_location = _search_with_fallback(
            query=str(args.get("query", "")).strip(),
            location=str(args.get("location", "desktop")).strip() or "desktop",
            extension=str(args.get("extension", "")).strip() or None,
        )
        return {"tool": "search_files", "items": items, "count": len(items), "resolved_location": resolved_location}
    if tool == "copy_file":
        items, resolved_location = _search_with_fallback(
            query=str(args.get("query", "")).strip(),
            location=str(args.get("location", "desktop")).strip() or "desktop",
            extension=str(args.get("extension", "")).strip() or None,
        )
        if not items:
            raise ValueError("Kopyalanacak dosya bulunamadi.")
        selected = max(items, key=lambda item: item.get("modified_at", 0))
        copied = copy_file_to_location(
            str(selected["path"]),
            destination_location=str(args.get("destination_location", "desktop")).strip() or "desktop",
            allowed_folders=settings.allowed_folders,
        )
        return {"tool": "copy_file", "source_file": selected, "copied_file": copied, "resolved_location": resolved_location}
    if tool == "send_file":
        items, resolved_location = _search_with_fallback(
            query=str(args.get("query", "")).strip(),
            location=str(args.get("location", "desktop")).strip() or "desktop",
            extension=str(args.get("extension", "")).strip() or None,
        )
        if not items:
            raise ValueError("Gonderilecek dosya bulunamadi.")
        recipient = str(args.get("recipient", "")).strip()
        if not recipient:
            raise ValueError("Alici e-posta adresi gerekli.")
        selected = max(items, key=lambda item: item.get("modified_at", 0))
        send_email_with_attachment(
            recipient=recipient,
            subject="AI Destekli Teknik Destek Ajani",
            body="Istenen dosya ektedir.",
            file_path=str(selected["path"]),
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            sender=settings.default_mail_from,
            allowed_recipients=settings.mail_recipients_whitelist,
            mail_transport=settings.mail_transport,
            browser_channel=settings.playwright_browser_channel,
            user_data_dir=settings.playwright_user_data_dir,
            mail_url=settings.playwright_mail_url,
            headless=settings.playwright_headless,
        )
        return {"tool": "send_file", "recipient": recipient, "sent_file": selected, "status": "sent", "resolved_location": resolved_location}
    if tool == "list_scripts":
        items = list_scripts()
        return {"tool": "list_scripts", "items": items, "count": len(items)}
    if tool == "run_whitelisted_script":
        script_name = str(args.get("script_name", "")).strip()
        if not script_name:
            raise ValueError("Script adi gerekli.")
        return {"tool": "run_whitelisted_script", **run_script(script_name, allowed_scripts=settings.allowed_scripts)}
    if tool == "open_application":
        return _open_application(
            app_name=str(args.get("app_name", "")).strip(),
            target=str(args.get("target", "")).strip() or None,
        )
    if tool == "send_keys":
        return _send_keys(keys=str(args.get("keys", "")), press_enter=bool(args.get("press_enter", False)))
    if tool == "take_screenshot":
        return _take_screenshot(save_name=str(args.get("save_name", "")).strip() or None)
    if tool == "run_powershell":
        script = str(args.get("script", "")).strip()
        if not script:
            raise ValueError("run_powershell icin script gerekli.")
        return _run_powershell_script(script, summary="Generated script executed.")
    raise ValueError(f"Desteklenmeyen tool: {tool}")


def generate_and_run_script(
    instruction: str,
    *,
    api_key: str,
    model: str,
    allowed_folders: Iterable[str],
    forbidden_actions: Iterable[str],
) -> dict[str, object]:
    payload = generate_powershell_script_with_gemini(
        api_key=api_key,
        model=model,
        prompt=_build_generation_prompt(
            instruction,
            allowed_folders=allowed_folders,
            forbidden_actions=forbidden_actions,
        ),
    )
    summary = str(payload.get("summary", "")).strip()
    steps = payload.get("steps")
    if isinstance(steps, list) and steps:
        results: list[dict[str, object]] = []
        for step in steps:
            if not isinstance(step, dict):
                raise RuntimeError("Gemini tool step gecersiz.")
            results.append(_execute_tool_step(step))
        return {
            "summary": summary or "Tool plan executed.",
            "steps": results,
            "step_count": len(results),
        }

    legacy_script = str(payload.get("script", "")).strip()
    if not legacy_script:
        raise RuntimeError("Gemini bos arac plani uretti.")
    return _run_powershell_script(legacy_script, summary=summary)


def list_scripts(manifest_path: Path | None = None) -> list[dict[str, str]]:
    return ScriptAdapter(manifest_path=manifest_path).list_scripts()


def run_script(
    script_name: str,
    *,
    allowed_scripts: Iterable[str] | None = None,
    manifest_path: Path | None = None,
) -> dict[str, object]:
    result = ScriptAdapter(
        manifest_path=manifest_path,
        allowed_scripts=allowed_scripts,
    ).run(script_name)
    return {
        "script": result.script,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
