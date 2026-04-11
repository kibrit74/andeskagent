from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, cast

from adapters.file_adapter import copy_file_to_location, search_files
from adapters.file_adapter import create_folder_in_location
from adapters.file_adapter import create_text_file_in_directory
from adapters.file_adapter import find_file_in_directory, write_text_to_file
from adapters.desktop_adapter import click_ui, focus_window, list_windows, read_screen, take_screenshot, wait_for_window
from adapters.gemini_adapter import generate_powershell_script_with_gemini
from adapters.mail_adapter import send_email_with_attachment
from adapters.system_adapter import get_system_status
from core.config import load_settings
from core.workflows import WorkflowStep, execute_workflow

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
    script_catalog = load_settings().allowed_scripts
    return f"""
Sen Windows otomasyon arac planlayicisisin.
Kullanicinin istegini mevcut yerel araclarla yerine getirecek bir PLAN uret.
Amacin once en dar, en guvenli ve en deterministik tool planini secmektir.

Kurallar:
- Markdown kullanma.
- Sadece gecerli JSON don.
- JSON alanlari: summary, steps
- steps bir dizi olsun.
- Her step bir object olsun ve alanlari: tool, args
- summary kisa ama kesin olsun.
- Desteklenen tool degerleri:
  - get_system_status
  - search_files
  - copy_file
  - create_folder
  - send_file
  - list_scripts
  - run_whitelisted_script
  - open_application
  - list_windows
  - focus_window
  - wait_for_window
  - click_ui
  - take_screenshot
  - read_screen
  - send_keys
  - run_powershell
- YALNIZCA bu toollar mevcut. MCP, plugin, remote browser agent, HTTP client, database client veya baska bir harici executor varmis gibi davranma.
- Kullanici istegini script yazarak cozmeye kosma; once uygun tool sec.
- Basit bir istek tek tool ile cozulebiliyorsa tek step don.
- Birden fazla step ancak gercekten gerekiyorsa don.
- Ayni amac mevcut bir tool ile cozulebiliyorsa run_powershell kullanma.
- run_powershell sadece su durumlarda kullan:
  - yerlesik tool seti istegi ifade etmeye yetmiyorsa
  - mantiksal kontrol, dongu, pencere/COM otomasyonu veya yerel OS seviyesi islem gerekiyorsa
  - mevcut tool zinciri gercekten yetersizse
- Kullanici sistem bilgisi istiyorsa get_system_status kullan.
- Kullanici dosya ariyorsa search_files kullan.
- Kullanici dosya kopyalamak istiyorsa copy_file kullan.
- Kullanici yeni klasor olusturmak istiyorsa create_folder kullan.
- Kullanici dosya gondermek istiyorsa send_file kullan.
- Kullanici script listesini istiyorsa list_scripts kullan.
- Kullanici whitelist script calistirmak istiyorsa run_whitelisted_script kullan.
- Kullanici bir uygulama acmak istiyorsa open_application kullan.
- Kullanici gorunen pencereleri listelemek istiyorsa list_windows kullan.
- Kullanici belirli bir pencereye gecmek istiyorsa focus_window kullan.
- Kullanici belirli bir pencerenin acilmasini beklemek istiyorsa wait_for_window kullan.
- Kullanici belirli koordinata tiklamak istiyorsa click_ui kullan.
- Kullanici ekran resmi istiyorsa take_screenshot kullan.
- Kullanici ekranda ne oldugunu anlamak istiyorsa read_screen kullan.
- Kullanici arayuzde yazi yazmak (type) veya Enter'a basmak istiyorsa send_keys kullan.
- Kullanici hem acma hem yazi yazma istiyorsa iki step don: once open_application sonra send_keys.
- Eger kullanici mantiksel kontroller (bul, bulamazsan bildir, ekle), sistem veya donanim islemleri istiyorsa genelde run_powershell gerekir; ancak mevcut tool seti yeterliyse onu tercih et.
- Diger araclar sadece basit/statik ihtiyaclar veya mevcut scriptler icin kullanilmalidir.
- Tool secim onceligi:
  1. get_system_status / search_files / copy_file / create_folder / send_file / list_scripts
  2. run_whitelisted_script
  3. open_application + list_windows + focus_window + wait_for_window + click_ui + read_screen + send_keys + take_screenshot
  4. run_powershell
- search_files args:
  - query
  - location: desktop, documents, downloads
  - extension: opsiyonel, noktasiz
- copy_file args:
  - query
  - location
  - extension
  - destination_location: desktop, documents, downloads
- create_folder args:
  - folder_name
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
- list_windows args bos olabilir.
- focus_window args:
  - title_contains: opsiyonel
  - process_name: opsiyonel
- wait_for_window args:
  - title_contains: opsiyonel
  - process_name: opsiyonel
  - timeout_seconds: opsiyonel
- click_ui args:
  - x: opsiyonel
  - y: opsiyonel
  - text: opsiyonel, UI eleman metni
  - title_contains: opsiyonel
  - process_name: opsiyonel
  - button: left veya right, opsiyonel
- take_screenshot args:
  - save_name: opsiyonel png dosya adi
- read_screen args:
  - save_name: opsiyonel png dosya adi
- send_keys args:
  - keys: Gonderilecek yazi metni
  - press_enter: true veya false. Eger islem sonunda onaylamak, gondermek veya mesaj atmak icin Enter'a basilmasi gerekiyorsa KESINLIKLE true don.
- run_powershell args:
  - script: tek basina calisabilir PowerShell script
- Uygulama ici ileri otomasyonlar icin, ornegin Outlook COM ile mail olusturma/gonderme gibi durumlarda run_powershell kullan.
- Bir istek belirli bir Windows uygulamasi icinde alan doldurma, mail gonderme, pencere kontrolu veya COM otomasyonu gerektiriyorsa run_powershell tercih et.
- Fakat eger kullanici sadece "Outlooku ac", "Chrome'u ac", "Notepad ac" diyorsa SADECE open_application kullan; COM scripti yazma.
- Bir uygulama acildiktan sonra onun gorunur olmasi gerekiyorsa open_application sonrasina wait_for_window veya focus_window ekleyebilirsin.
- Ekrandaki durumu anlamak icin OCR uydurma; bunun yerine read_screen kullan. read_screen gorunen pencere listesini, ekran goruntusunu ve UIAutomation ile toplanabilen metinleri verir.
- Koordinat bilmiyorsan click_ui icin once read_screen veya wait_for_window/focus_window kullan; sonra click_ui icinde text + process_name/title_contains ile hedefle.
- Eger kullanici sadece yeni klasor olusturmak istiyorsa create_folder kullan; Outlook, COM veya run_powershell kullanma.
- Eger kullanici "masaustune yeni klasor olustur" benzeri net bir komut verirse create_folder ile yanit ver.
- Eger kullanici mcp, plugin, server tool veya agent istiyorsa ve bunu yerel toollar ile gercekleyemiyorsan run_powershell de uydurma; o durumda en yakin yerel plan yoksa summary'de siniri belirt ve bos olmayan ama guvenli bir steps plani olarak en fazla open_application gibi ilgili yerel adimlar kullan. Hicbir yerel karsiligi yoksa run_powershell ile sahte entegrasyon yazma.
- Silme, registry degistirme, network ayari degistirme, formatlama, yeniden baslatma yapma.
- Sadece su klasorlerde dosya islemi yap: {", ".join(allowed_folders)}
- Asla su yasakli aksiyonlari yapma: {", ".join(forbidden_actions)}
- Mumkunse var olan dosyayi koruyup kopya/olusturma mantigi kullan.
- Mevcut whitelist script adlari: {", ".join(script_catalog[:80]) if script_catalog else "Yok"}

Planlama ornekleri:
- "masaustune yeni klasor olustur" => {{"summary":"Masaustunde yeni klasor olusturulacak.","steps":[{{"tool":"create_folder","args":{{"folder_name":"Yeni Klasor","destination_location":"desktop"}}}}]}}
- "chromeu ac ve openai sitesine git" => {{"summary":"Chrome acilacak.","steps":[{{"tool":"open_application","args":{{"app_name":"chrome","target":"https://openai.com"}}}},{{"tool":"wait_for_window","args":{{"process_name":"chrome","timeout_seconds":20}}}}]}}
- "outlooku ac" => {{"summary":"Outlook acilacak.","steps":[{{"tool":"open_application","args":{{"app_name":"outlook"}}}}]}}
- "gorunen pencereleri listele" => {{"summary":"Gorunen pencereler listelenecek.","steps":[{{"tool":"list_windows","args":{{}}}}]}}
- "Outlook'ta Gonder butonuna tikla" => {{"summary":"Outlook icindeki hedef buton tiklanacak.","steps":[{{"tool":"focus_window","args":{{"process_name":"outlook"}}}},{{"tool":"click_ui","args":{{"text":"Gonder","process_name":"outlook","button":"left"}}}}]}}
- "ekrani oku" => {{"summary":"Ekran durumu toplanacak.","steps":[{{"tool":"read_screen","args":{{"save_name":"screen-state.png"}}}}]}}
- "masaustumdeki pdf dosyalarini ara" => {{"summary":"PDF dosyalari aranacak.","steps":[{{"tool":"search_files","args":{{"query":"","location":"desktop","extension":"pdf"}}}}]}}

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
    if tool == "create_folder":
        created = create_folder_in_location(
            str(args.get("folder_name", "")).strip() or "Yeni Klasor",
            destination_location=str(args.get("destination_location", "desktop")).strip() or "desktop",
            allowed_folders=settings.allowed_folders,
        )
        return {"tool": "create_folder", "created_folder": created, "status": "created"}
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
    if tool == "list_windows":
        return {"tool": "list_windows", **list_windows()}
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
    if tool == "focus_window":
        return {
            "tool": "focus_window",
            **focus_window(
                title_contains=str(args.get("title_contains", "")).strip() or None,
                process_name=str(args.get("process_name", "")).strip() or None,
            ),
        }
    if tool == "wait_for_window":
        return {
            "tool": "wait_for_window",
            **wait_for_window(
                title_contains=str(args.get("title_contains", "")).strip() or None,
                process_name=str(args.get("process_name", "")).strip() or None,
                timeout_seconds=int(args.get("timeout_seconds", 20) or 20),
            ),
        }
    if tool == "click_ui":
        x = args.get("x")
        y = args.get("y")
        return {
            "tool": "click_ui",
            **click_ui(
                x=int(x) if x is not None else None,
                y=int(y) if y is not None else None,
                button=str(args.get("button", "left")).strip() or "left",
                text=str(args.get("text", "")).strip() or None,
                title_contains=str(args.get("title_contains", "")).strip() or None,
                process_name=str(args.get("process_name", "")).strip() or None,
            ),
        }
    if tool == "send_keys":
        return _send_keys(keys=str(args.get("keys", "")), press_enter=bool(args.get("press_enter", False)))
    if tool == "take_screenshot":
        return take_screenshot(save_name=str(args.get("save_name", "")).strip() or None)
    if tool == "read_screen":
        return read_screen(save_name=str(args.get("save_name", "")).strip() or None)
    if tool == "run_powershell":
        script = str(args.get("script", "")).strip()
        if not script:
            raise ValueError("run_powershell icin script gerekli.")
        return _run_powershell_script(script, summary="Generated script executed.")
    raise ValueError(f"Desteklenmeyen tool: {tool}")


def _looks_like_python_command_repair(instruction: str) -> bool:
    normalized = instruction.lower()
    python_markers = ("python", "py.exe", "python.exe", "0xc0000142")
    issue_markers = (
        "calismiyor",
        "acilmiyor",
        "bozuk",
        "duzelt",
        "duzelsin",
        "fix",
        "uygulama hatasi",
        "baslatilamadi",
        "failed to run",
        "sistem dosyaya erisemiyor",
        "path",
        "alias",
    )
    return any(marker in normalized for marker in python_markers) and any(
        marker in normalized for marker in issue_markers
    )


def _list_python_candidates() -> list[Path]:
    local_python = Path(os.environ.get("LOCALAPPDATA", "")) / "Python"
    preferred = [
        local_python / "bin" / "python.exe",
        local_python / "pythoncore-3.14-64" / "python.exe",
    ]
    discovered = [candidate for candidate in preferred if candidate.exists()]
    if discovered:
        return discovered

    return sorted(
        [
            item
            for item in local_python.rglob("python.exe")
            if item.is_file() and "WindowsApps" not in str(item)
        ],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def _read_user_path() -> str:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as key:
        try:
            value, _ = winreg.QueryValueEx(key, "Path")
            return str(value or "")
        except FileNotFoundError:
            return ""


def _write_user_path(path_value: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, path_value)


def _workflow_detect_python(context: dict[str, object]) -> dict[str, object]:
    candidates = _list_python_candidates()
    if not candidates:
        raise RuntimeError("Calisan python.exe bulunamadi.")
    candidate = candidates[0]
    return {"python_path": str(candidate), "candidate_count": len(candidates)}


def _workflow_prepare_python_shim_dir(context: dict[str, object]) -> dict[str, object]:
    local_python = Path(os.environ.get("LOCALAPPDATA", "")) / "Python"
    shim_dir = local_python / "shim"
    shim_dir.mkdir(parents=True, exist_ok=True)
    return {"shim_dir": str(shim_dir)}


def _workflow_write_python_shims(context: dict[str, object]) -> dict[str, object]:
    python_path = str(context.get("python_path", "")).strip()
    shim_dir_raw = str(context.get("shim_dir", "")).strip()
    if not python_path or not shim_dir_raw:
        raise RuntimeError("Shim olusturma icin gerekli context eksik.")

    shim_dir = Path(shim_dir_raw)
    command_text = f'@echo off\r\n"{python_path}" %*\r\n'
    python_cmd = shim_dir / "python.cmd"
    py_cmd = shim_dir / "py.cmd"
    python_cmd.write_text(command_text, encoding="ascii")
    py_cmd.write_text(command_text, encoding="ascii")
    return {"created_files": [str(python_cmd), str(py_cmd)]}


def _workflow_update_user_path(context: dict[str, object]) -> dict[str, object]:
    shim_dir = str(context.get("shim_dir", "")).strip()
    if not shim_dir:
        raise RuntimeError("PATH guncelleme icin shim klasoru bulunamadi.")

    user_path = _read_user_path()
    if not user_path:
        new_user_path = shim_dir
    elif shim_dir.lower() not in user_path.lower():
        new_user_path = f"{shim_dir};{user_path}"
    else:
        new_user_path = user_path

    _write_user_path(new_user_path)
    os.environ["PATH"] = f"{shim_dir};{os.environ.get('PATH', '')}"
    return {"path_updated": True, "user_path": new_user_path}


def _extract_known_app_name(instruction: str) -> str | None:
    normalized = instruction.lower()
    app_markers = {
        "chrome": ("chrome", "google chrome"),
        "msedge": ("edge", "microsoft edge"),
        "outlook": ("outlook", "outlok"),
        "excel": ("excel",),
        "word": ("word",),
        "notepad": ("notepad", "not defteri"),
        "calc": ("hesap makinesi", "calculator", "calc"),
        "mspaint": ("paint", "mspaint"),
        "explorer": ("explorer", "dosya gezgini"),
    }
    for app_name, markers in app_markers.items():
        if any(marker in normalized for marker in markers):
            return app_name
    return None


def _browser_process_name(settings: Any) -> str:
    channel = str(getattr(settings, "playwright_browser_channel", "msedge") or "msedge").strip().lower()
    if channel in {"chrome", "google chrome"}:
        return "chrome"
    if channel in {"edge", "msedge", "microsoft edge"}:
        return "msedge"
    return channel or "msedge"


def _looks_like_mail_session_workflow(instruction: str) -> bool:
    normalized = instruction.lower()
    mail_markers = ("gmail", "mail", "eposta", "e-posta", "outlook")
    issue_markers = ("oturum", "giris", "login", "hazir", "compose", "gonderem", "send", "session")
    return any(marker in normalized for marker in mail_markers) and any(marker in normalized for marker in issue_markers)


def _looks_like_window_guidance_workflow(instruction: str) -> bool:
    normalized = instruction.lower()
    if " ve " not in normalized and " sonra " not in normalized and " ardindan " not in normalized:
        return False
    has_app = _extract_known_app_name(normalized) is not None
    has_followup = any(marker in normalized for marker in ("odak", "gec", "bekle", "ekrani oku", "screenshot", "ekran resmi", "yaz"))
    return has_app and has_followup


def _looks_like_folder_and_text_file_workflow(instruction: str) -> bool:
    normalized = instruction.lower()
    has_folder = "klasor" in normalized or "folder" in normalized
    has_text_file = any(token in normalized for token in ("txt", "metin dosyasi", "txt dosyasi"))
    has_create = any(token in normalized for token in ("ekle", "olustur", "ac", "yarat"))
    return has_folder and has_text_file and has_create


def _looks_like_write_text_into_file_workflow(instruction: str) -> bool:
    normalized = instruction.lower()
    return "dosyasina" in normalized and any(token in normalized for token in (" yaz", "ekle", "icerigini yaz", "metin ekle"))


def _extract_folder_and_text_file_names(instruction: str) -> tuple[str, str]:
    normalized = instruction.lower()
    folder_name = "Yeni Klasor"
    file_name = "Yeni Metin Belgesi.txt"

    match = re.search(r"'([^']+)'\s+isimli\s+klasor", instruction, flags=re.IGNORECASE)
    if match:
        folder_name = match.group(1).strip() or folder_name
    elif "yeni klasor" in normalized:
        folder_name = "Yeni Klasor"

    file_match = re.search(r"'([^']+)'\s+isimli\s+(?:txt|metin)\s+dosy", instruction, flags=re.IGNORECASE)
    if file_match:
        candidate = file_match.group(1).strip()
        if candidate:
            file_name = candidate if candidate.lower().endswith(".txt") else f"{candidate}.txt"

    return folder_name, file_name


def _extract_write_target(instruction: str) -> tuple[str, str, str]:
    normalized = instruction.lower()
    folder_name = "Yeni Klasor"
    file_name = "Yeni Metin Belgesi.txt"
    content = ""

    folder_match = re.search(r"(.+?)\s+deki\s+.+?\s+dosyasina", instruction, flags=re.IGNORECASE)
    if folder_match:
        folder_name = folder_match.group(1).strip()

    file_match = re.search(r"deki\s+(.+?)\s+dosyasina", instruction, flags=re.IGNORECASE)
    if file_match:
        candidate = file_match.group(1).strip()
        if candidate:
            file_name = candidate if candidate.lower().endswith(".txt") else f"{candidate}.txt"

    quoted = re.search(r'"([^"]+)"', instruction)
    if quoted:
        content = quoted.group(1).strip()
    else:
        tail_match = re.search(r"dosyasina\s+(.+?)\s+yaz", instruction, flags=re.IGNORECASE)
        if tail_match:
            content = tail_match.group(1).strip()

    if not content:
        content = instruction.strip()

    return folder_name, file_name, content


def _mail_session_workflow() -> dict[str, object]:
    settings = load_settings()
    browser_app = _browser_process_name(settings)
    execution = execute_workflow(
        summary="Mail oturumu icin hazirlama zinciri calistirildi.",
        initial_context={},
        steps=[
            WorkflowStep(
                id="open_mail",
                title="Mail penceresini ac",
                run=lambda context: _open_application(app_name=browser_app, target=settings.playwright_mail_url),
            ),
            WorkflowStep(
                id="wait_window",
                title="Mail penceresinin gelmesini bekle",
                run=lambda context: wait_for_window(process_name=browser_app, timeout_seconds=25),
            ),
            WorkflowStep(
                id="focus_window",
                title="Mail penceresine odaklan",
                run=lambda context: focus_window(process_name=browser_app),
            ),
            WorkflowStep(
                id="read_screen",
                title="Ekran durumunu topla",
                run=lambda context: read_screen(save_name="mail-session-check"),
                continue_on_error=True,
            ),
        ],
    )
    return {
        "summary": execution.summary,
        "steps": execution.steps,
        "step_count": len(execution.steps),
        "status": "fixed" if execution.success else "partial",
    }


def _window_guidance_workflow(instruction: str) -> dict[str, object]:
    normalized = instruction.lower()
    app_name = _extract_known_app_name(normalized)
    if not app_name:
        raise RuntimeError("Zincirleme pencere akisi icin uygulama anlasilmadi.")

    steps: list[WorkflowStep] = [
        WorkflowStep(
            id="open_application",
            title="Uygulamayi ac",
            run=lambda context: _open_application(app_name=app_name),
        ),
        WorkflowStep(
            id="wait_window",
            title="Pencerenin gelmesini bekle",
            run=lambda context: wait_for_window(process_name=app_name, timeout_seconds=20),
        ),
        WorkflowStep(
            id="focus_window",
            title="Pencereye odaklan",
            run=lambda context: focus_window(process_name=app_name),
        ),
    ]

    if any(marker in normalized for marker in ("ekrani oku", "screenshot", "ekran resmi")):
        steps.append(
            WorkflowStep(
                id="read_screen",
                title="Ekran durumunu topla",
                run=lambda context: read_screen(save_name=f"{app_name}-workflow"),
                continue_on_error=True,
            )
        )

    execution = execute_workflow(
        summary="Pencere odakli is akisi calistirildi.",
        initial_context={"app_name": app_name},
        steps=steps,
    )
    return {
        "summary": execution.summary,
        "steps": execution.steps,
        "step_count": len(execution.steps),
        "status": "success" if execution.success else "partial",
        "app_name": app_name,
    }


def _folder_and_text_file_workflow(instruction: str) -> dict[str, object]:
    destination_location = "desktop"
    if "documents" in instruction.lower() or "belgeler" in instruction.lower():
        destination_location = "documents"
    elif "downloads" in instruction.lower() or "indirilen" in instruction.lower():
        destination_location = "downloads"

    folder_name, file_name = _extract_folder_and_text_file_names(instruction)
    settings = load_settings()

    execution = execute_workflow(
        summary="Klasor ve metin dosyasi olusturma zinciri calistirildi.",
        initial_context={"destination_location": destination_location, "folder_name": folder_name, "file_name": file_name},
        steps=[
            WorkflowStep(
                id="create_folder",
                title="Klasoru olustur",
                run=lambda context: {
                    "created_folder": create_folder_in_location(
                        str(context["folder_name"]),
                        destination_location=str(context["destination_location"]),
                        allowed_folders=settings.allowed_folders,
                    )
                },
                verify=lambda context, result: bool(result and result.get("created_folder")),
            ),
            WorkflowStep(
                id="create_text_file",
                title="Klasor icine txt dosyasi ekle",
                run=lambda context: {
                    "created_file": create_text_file_in_directory(
                        str(context["created_folder"]["path"]),
                        file_name=str(context["file_name"]),
                        allowed_folders=settings.allowed_folders,
                    )
                },
                verify=lambda context, result: bool(result and result.get("created_file")),
            ),
        ],
    )

    return {
        "summary": execution.summary,
        "steps": execution.steps,
        "step_count": len(execution.steps),
        "status": "success" if execution.success else "partial",
        "folder_name": folder_name,
        "file_name": file_name,
        "destination_location": destination_location,
    }


def _write_text_into_file_workflow(instruction: str) -> dict[str, object]:
    folder_name, file_name, content = _extract_write_target(instruction)
    destination_location = "desktop"
    if "documents" in instruction.lower() or "belgeler" in instruction.lower():
        destination_location = "documents"
    elif "downloads" in instruction.lower() or "indirilen" in instruction.lower():
        destination_location = "downloads"

    settings = load_settings()
    base_dir = Path.home() / ("Desktop" if destination_location == "desktop" else "Documents" if destination_location == "documents" else "Downloads")
    target_dir = base_dir / folder_name

    execution = execute_workflow(
        summary="Dosyaya yazi yazma zinciri calistirildi.",
        initial_context={
            "folder_name": folder_name,
            "file_name": file_name,
            "content": content,
            "destination_location": destination_location,
            "target_dir": str(target_dir),
        },
        steps=[
            WorkflowStep(
                id="ensure_folder",
                title="Hedef klasoru dogrula",
                run=lambda context: {
                    "folder": {"path": str(target_dir), "name": folder_name, "location": destination_location}
                } if Path(str(context["target_dir"])).exists() else {
                    "folder": create_folder_in_location(
                        str(context["folder_name"]),
                        destination_location=str(context["destination_location"]),
                        allowed_folders=settings.allowed_folders,
                    )
                },
                verify=lambda context, result: bool(result and result.get("folder")),
            ),
            WorkflowStep(
                id="ensure_text_file",
                title="Metin dosyasini bul veya olustur",
                run=lambda context: {
                    "file": find_file_in_directory(
                        str(context["folder"]["path"]),
                        Path(str(context["file_name"])).stem,
                        extension="txt",
                        allowed_folders=settings.allowed_folders,
                    ) or create_text_file_in_directory(
                        str(context["folder"]["path"]),
                        file_name=str(context["file_name"]),
                        allowed_folders=settings.allowed_folders,
                    )
                },
                verify=lambda context, result: bool(result and result.get("file")),
            ),
            WorkflowStep(
                id="write_text",
                title="Dosyaya metni yaz",
                run=lambda context: {
                    "written_file": write_text_to_file(
                        str(context["file"]["path"]),
                        str(context["content"]),
                        allowed_folders=settings.allowed_folders,
                    )
                },
                verify=lambda context, result: bool(result and result.get("written_file")),
            ),
        ],
    )

    return {
        "summary": execution.summary,
        "steps": execution.steps,
        "step_count": len(execution.steps),
        "status": "success" if execution.success else "partial",
        "folder_name": folder_name,
        "file_name": file_name,
        "content": content,
        "destination_location": destination_location,
    }


def _repair_python_command_resolution() -> dict[str, object]:
    execution = execute_workflow(
        summary="Python komutu icin zincirleme onarim uygulandi.",
        initial_context={},
        steps=[
            WorkflowStep(
                id="detect_python",
                title="Calisan Python binary dosyasini bul",
                run=_workflow_detect_python,
                verify=lambda context, result: bool(result and result.get("python_path")),
            ),
            WorkflowStep(
                id="prepare_shim_dir",
                title="Komut yonlendirme klasorunu hazirla",
                run=_workflow_prepare_python_shim_dir,
                verify=lambda context, result: bool(result and result.get("shim_dir")),
            ),
            WorkflowStep(
                id="write_shims",
                title="python ve py shim dosyalarini olustur",
                run=_workflow_write_python_shims,
                verify=lambda context, result: bool(result and result.get("created_files")),
            ),
            WorkflowStep(
                id="update_user_path",
                title="Kullanici PATH degiskenini guncelle",
                run=_workflow_update_user_path,
                verify=lambda context, result: bool(result and result.get("path_updated")),
            ),
        ],
    )

    return {
        "summary": execution.summary,
        "steps": execution.steps,
        "step_count": len(execution.steps),
        "status": "fixed" if execution.success else "partial",
        "python_path": execution.context.get("python_path"),
        "shim_dir": execution.context.get("shim_dir"),
        "created_files": execution.context.get("created_files"),
        "next_steps": [
            "Acik terminal pencerelerini kapat.",
            "Yeni bir terminal ac.",
            "python --version komutunu tekrar calistir.",
        ],
    }


def generate_and_run_script(
    instruction: str,
    *,
    api_key: str,
    model: str,
    allowed_folders: Iterable[str],
    forbidden_actions: Iterable[str],
) -> dict[str, object]:
    if _looks_like_python_command_repair(instruction):
        return _repair_python_command_resolution()
    if _looks_like_write_text_into_file_workflow(instruction):
        return _write_text_into_file_workflow(instruction)
    if _looks_like_folder_and_text_file_workflow(instruction):
        return _folder_and_text_file_workflow(instruction)
    if _looks_like_mail_session_workflow(instruction):
        return _mail_session_workflow()
    if _looks_like_window_guidance_workflow(instruction):
        return _window_guidance_workflow(instruction)

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
