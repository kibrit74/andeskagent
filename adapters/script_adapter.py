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

from adapters.file_adapter import copy_file_to_location, location_to_path, search_files
from adapters.file_adapter import create_folder_in_location
from adapters.file_adapter import create_text_file_in_directory
from adapters.file_adapter import find_file_in_directory, write_text_to_file
from adapters.file_adapter import copy_files_to_path, move_files_to_path, zip_directory, filter_files_by_date
from adapters.desktop_adapter import click_ui, focus_window, list_windows, read_screen, take_screenshot, wait_for_window
from adapters.gemini_adapter import generate_powershell_script_with_gemini
from adapters.openrouter_adapter import generate_powershell_script_with_openrouter
from adapters.openrouter_adapter import generate_powershell_script_with_openrouter
from adapters.mail_adapter import send_email_with_attachment
from adapters.system_adapter import get_system_status
from core.config import load_settings
from core.workflows import WorkflowStep, execute_workflow

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_PATH = BASE_DIR / "scripts" / "manifest.json"
PROJECT_CONTEXT_PATH = BASE_DIR / ".teknikajan.md"
FALLBACK_LOCATIONS = ("desktop", "documents", "downloads")


def _sanitize_excel_file_name(file_name: str) -> str:
    normalized_name = (file_name or "").strip().strip(".")
    if not normalized_name:
        normalized_name = "Excel-Workbook.xlsx"
    safe_name = "".join(char for char in normalized_name if char not in '<>:"/\\|?*').strip() or "Excel-Workbook.xlsx"
    if not safe_name.lower().endswith(".xlsx"):
        safe_name += ".xlsx"
    return safe_name


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
    workflow_profile: str | None,
    allowed_folders: Iterable[str],
    forbidden_actions: Iterable[str],
) -> str:
    script_catalog = load_settings().allowed_scripts
    project_context = ""
    if PROJECT_CONTEXT_PATH.exists():
        try:
            content = PROJECT_CONTEXT_PATH.read_text(encoding="utf-8").strip()
            if content:
                project_context = content[:2000]
        except OSError:
            project_context = ""
    profile_guidance = {
        "file_chain": """
Workflow profile: file_chain
- Sadece dosya/klasor/mail zinciri toollarina odaklan.
- Once search_files/filter_by_date/create_folder, sonra copy/move, sonra zip, en son send_file_by_path.
- Bu profilde UI otomasyonu ve run_powershell ancak tool seti kesin yetmiyorsa kullan.
""".strip(),
        "excel_workflow": """
Workflow profile: excel_workflow
- Excel islemlerinde once native Excel toollarini kullan: create_excel_workbook, write_excel_cells, save_excel_workbook.
- Excel veri girisi icin open_application, click_ui, send_keys veya run_powershell ile serbest UI otomasyonu kurma.
- Hucre yazma gerekiyorsa cells listesi ile write_excel_cells kullan.
""".strip(),
        "app_control": """
Workflow profile: app_control
- Uygulama/pencere kontrolu icin open_application, wait_for_window, focus_window, click_ui, send_keys kullan.
- Bu profilde dosya arama/zip/mail zincirine sapma.
""".strip(),
        "screen_inspect": """
Workflow profile: screen_inspect
- read_screen, take_screenshot ve verify_ui_state araclarini tercih et.
- Bu profilde dosya zinciri veya Office duzenleme planlama.
""".strip(),
        "system_repair": """
Workflow profile: system_repair
- get_system_status, run_whitelisted_script ve mevcut deterministic repair workflow'larini tercih et.
- Bu profilde rastgele dosya/mail/UI planina sapma.
""".strip(),
    }.get(workflow_profile or "", "Workflow profile: generic")
    return f"""
Sen Windows otomasyon arac planlayicisisin.
Kullanicinin istegini mevcut yerel araclarla yerine getirecek bir PLAN uret.
Amacin once en dar, en guvenli ve en deterministik tool planini secmektir.

{profile_guidance}

Proje baglami (.teknikajan.md):
{project_context or "Yok"}

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
  - copy_files_to_path
  - move_files_to_path
  - zip_folder
  - filter_by_date
  - send_file_by_path
  - create_excel_workbook
  - write_excel_cells
  - save_excel_workbook
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
- Excel/Word/Outlook gibi Office uygulamalarinda belge icerigi duzenleme, hucre/sutun basligi yazma, calisma kitabi olusturma veya kaydetme gibi deterministik veri girisi islerinde open_application + send_keys yerine run_powershell tercih et.
- Eger kullanici mantiksel kontroller (bul, bulamazsan bildir, ekle), sistem veya donanim islemleri istiyorsa genelde run_powershell gerekir; ancak mevcut tool seti yeterliyse onu tercih et.
- Diger araclar sadece basit/statik ihtiyaclar veya mevcut scriptler icin kullanilmalidir.
- Tool secim onceligi:
  1. get_system_status / search_files / copy_file / create_folder / send_file / list_scripts / filter_by_date / copy_files_to_path / move_files_to_path / zip_folder / send_file_by_path / create_excel_workbook / write_excel_cells / save_excel_workbook
  2. run_whitelisted_script
  3. open_application + list_windows + focus_window + wait_for_window + click_ui + read_screen + send_keys + take_screenshot
  4. run_powershell

ADIMLAR ARASI VERI AKTARIMI ($ref sistemi):
- Bir step'in ciktisina sonraki step'ten "$ref:anahtar" ile erisebilirsin.
- Kisa erisim anahtarlari (context icerisinde otomatik olusur):
  - $ref:last_folder_path   -> Son olusturulan klasorun mutlak yolu
  - $ref:last_items          -> Son bulunan/filtrelenen dosya listesi (array)
  - $ref:last_zip_path       -> Son olusturulan zip dosyasinin mutlak yolu
  - $ref:last_path           -> Son islenen dosyanin mutlak yolu
  - $ref:known_paths.desktop -> Desktop klasorunun mutlak yolu
  - $ref:known_paths.documents -> Documents klasorunun mutlak yolu
  - $ref:known_paths.downloads -> Downloads klasorunun mutlak yolu
- Detayli erisim: $ref:create_folder_result.created_folder.path
- $ref degerleri SADECE string olarak kullan: "$ref:last_items"
- Zincirleme islemlerde MUTLAKA $ref kullan! Sabit yol yazma.

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
- copy_files_to_path args:
  - file_paths: dosya yolu listesi VEYA "$ref:last_items" (otomatik path cikarir)
  - destination_path: mutlak klasor yolu VEYA "$ref:last_folder_path"
- move_files_to_path args:
  - file_paths: dosya yolu listesi VEYA "$ref:last_items" (otomatik path cikarir)
  - destination_path: mutlak klasor yolu VEYA "$ref:last_folder_path"
- zip_folder args:
  - folder_path: mutlak klasor yolu VEYA "$ref:last_folder_path"
  - output_name: opsiyonel zip dosya adi
- filter_by_date args:
  - files: dosya listesi VEYA "$ref:last_items"
  - month: 1-12 (opsiyonel)
  - year: 2024, 2025, 2026, vb (opsiyonel, yoksa guncel yil)
- send_file_by_path args:
  - file_path: mutlak dosya yolu VEYA "$ref:last_zip_path" VEYA "$ref:last_path"
  - recipient: e-posta adresi
- create_excel_workbook args:
  - file_name: opsiyonel xlsx dosya adi
  - destination_location: desktop, documents, downloads
- write_excel_cells args:
  - file_path: mutlak dosya yolu VEYA "$ref:last_path"
  - cells: [{{"cell":"A1","value":"Baslik"}}] formatinda hucre listesi
- save_excel_workbook args:
  - file_path: mutlak dosya yolu VEYA "$ref:last_path"
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
  - mode: fast, medium, full
- send_keys args:
  - keys: Gonderilecek yazi metni
  - press_enter: true veya false. Eger islem sonunda onaylamak, gondermek veya mesaj atmak icin Enter'a basilmasi gerekiyorsa KESINLIKLE true don.
- run_powershell args:
  - script: tek basina calisabilir PowerShell script. ONEMLI: PowerShell'de COM objeleri veya arrayler ile calisirken (ornegin $folder.Items), '1..5' gibi eleman sayisindan bagimsiz donguler kurma! DAIMA eleman sayisi sinirini kontrol et (Array index out of bounds hatalarini engelle). Ornek: `$count = [Math]::Min($items.Count, 5); if ($count -gt 0) {{ 1..$count | ForEach-Object {{ ... }} }}`
- Uygulama ici ileri otomasyonlar icin, ornegin Outlook COM ile mail olusturma/gonderme gibi durumlarda run_powershell kullan.
- Bir istek belirli bir Windows uygulamasi icinde alan doldurma, mail gonderme, pencere kontrolu veya COM otomasyonu gerektiriyorsa run_powershell tercih et.
- Fakat eger kullanici sadece \"Outlooku ac\", \"Chrome'u ac\", \"Notepad ac\" diyorsa SADECE open_application kullan; COM scripti yazma.
- Bir uygulama acildiktan sonra onun gorunur olmasi gerekiyorsa open_application sonrasina wait_for_window veya focus_window ekleyebilirsin.
- Ekrandaki durumu anlamak icin OCR uydurma; bunun yerine read_screen kullan. read_screen modlari:
  - fast: aktif pencere + gorunen pencereler
  - medium: fast + screenshot
  - full: medium + UIAutomation + OCR
- Koordinat bilmiyorsan click_ui icin once read_screen veya wait_for_window/focus_window kullan; sonra click_ui icinde text + process_name/title_contains ile hedefle.
- Eger kullanici sadece yeni klasor olusturmak istiyorsa create_folder kullan; Outlook, COM veya run_powershell kullanma.
- Eger kullanici \"masaustune yeni klasor olustur\" benzeri net bir komut verirse create_folder ile yanit ver.
- Eger kullanici mcp, plugin, server tool veya agent istiyorsa ve bunu yerel toollar ile gercekleyemiyorsan run_powershell de uydurma; o durumda en yakin yerel plan yoksa summary'de siniri belirt ve bos olmayan ama guvenli bir steps plani olarak en fazla open_application gibi ilgili yerel adimlar kullan. Hicbir yerel karsiligi yoksa run_powershell ile sahte entegrasyon yazma.
- Silme, registry degistirme, network ayari degistirme, formatlama, yeniden baslatma yapma.
- Sadece su klasorlerde dosya islemi yap: {", ".join(allowed_folders)}
- Asla su yasakli aksiyonlari yapma: {", ".join(forbidden_actions)}
- Mumkunse var olan dosyayi koruyup kopya/olusturma mantigi kullan.
- Mevcut whitelist script adlari: {", ".join(script_catalog[:80]) if script_catalog else "Yok"}

Planlama ornekleri:
- \"masaustune yeni klasor olustur\" => {{\"summary\":\"Masaustunde yeni klasor olusturulacak.\",\"steps\":[{{\"tool\":\"create_folder\",\"args\":{{\"folder_name\":\"Yeni Klasor\",\"destination_location\":\"desktop\"}}}}]}}
- \"chromeu ac ve openai sitesine git\" => {{\"summary\":\"Chrome acilacak.\",\"steps\":[{{\"tool\":\"open_application\",\"args\":{{\"app_name\":\"chrome\",\"target\":\"https://openai.com\"}}}},{{\"tool\":\"wait_for_window\",\"args\":{{\"process_name\":\"chrome\",\"timeout_seconds\":20}}}}]}}
- \"outlooku ac\" => {{\"summary\":\"Outlook acilacak.\",\"steps\":[{{\"tool\":\"open_application\",\"args\":{{\"app_name\":\"outlook\"}}}}]}}
- \"gorunen pencereleri listele\" => {{\"summary\":\"Gorunen pencereler listelenecek.\",\"steps\":[{{\"tool\":\"list_windows\",\"args\":{{}}}}]}}
- \"Outlook'ta Gonder butonuna tikla\" => {{\"summary\":\"Outlook icindeki hedef buton tiklanacak.\",\"steps\":[{{\"tool\":\"focus_window\",\"args\":{{\"process_name\":\"outlook\"}}}},{{\"tool\":\"click_ui\",\"args\":{{\"text\":\"Gonder\",\"process_name\":\"outlook\",\"button\":\"left\"}}}}]}}
- \"ekrani oku\" => {{\"summary\":\"Ekran durumu hizli sekilde toplanacak.\",\"steps\":[{{\"tool\":\"read_screen\",\"args\":{{\"mode\":\"medium\",\"save_name\":\"screen-state.png\"}}}}]}}
- \"masaustumdeki pdf dosyalarini ara\" => {{\"summary\":\"PDF dosyalari aranacak.\",\"steps\":[{{\"tool\":\"search_files\",\"args\":{{\"query\":\"\",\"location\":\"desktop\",\"extension\":\"pdf\"}}}}]}}
- \"Excel calisma kitabi ac, A1 hucresine Baslik, B1 hucresine Sozlesme Hesabi yaz ve kaydet\" => {{\"summary\":\"Excel calisma kitabi tool zinciri ile duzenlenecek.\",\"steps\":[{{\"tool\":\"create_excel_workbook\",\"args\":{{\"file_name\":\"Excel-Workbook.xlsx\",\"destination_location\":\"desktop\"}}}},{{\"tool\":\"write_excel_cells\",\"args\":{{\"file_path\":\"$ref:last_path\",\"cells\":[{{\"cell\":\"A1\",\"value\":\"Baslik\"}},{{\"cell\":\"B1\",\"value\":\"Sozlesme Hesabi\"}}]}}}},{{\"tool\":\"save_excel_workbook\",\"args\":{{\"file_path\":\"$ref:last_path\"}}}}]}}
- \"masaustune Masraflar klasoru olustur, mart ayindaki masraf excellerini bul, klasore kopyala, zipleyip ali@test.com adresine gonder\" => {{\"summary\":\"Masraflar klasoru olusturulup mart excelleri kopyalanip ziplenip gonderilecek.\",\"steps\":[{{\"tool\":\"create_folder\",\"args\":{{\"folder_name\":\"Masraflar\",\"destination_location\":\"desktop\"}}}},{{\"tool\":\"search_files\",\"args\":{{\"query\":\"masraf\",\"location\":\"desktop\",\"extension\":\"xlsx\"}}}},{{\"tool\":\"filter_by_date\",\"args\":{{\"files\":\"$ref:last_items\",\"month\":3}}}},{{\"tool\":\"copy_files_to_path\",\"args\":{{\"file_paths\":\"$ref:last_items\",\"destination_path\":\"$ref:last_folder_path\"}}}},{{\"tool\":\"zip_folder\",\"args\":{{\"folder_path\":\"$ref:last_folder_path\"}}}},{{\"tool\":\"send_file_by_path\",\"args\":{{\"file_path\":\"$ref:last_zip_path\",\"recipient\":\"ali@test.com\"}}}}]}}
- \"documentsdan butun pdfleri masaustune kopyala\" => {{\"summary\":\"Belgeler altindaki PDF dosyalari masaustune kopyalanacak.\",\"steps\":[{{\"tool\":\"search_files\",\"args\":{{\"query\":\"\",\"location\":\"documents\",\"extension\":\"pdf\"}}}},{{\"tool\":\"copy_files_to_path\",\"args\":{{\"file_paths\":\"$ref:last_items\",\"destination_path\":\"$ref:known_paths.desktop\"}}}}]}}

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


def _open_application(*, app_name: str, target: str | None = None, profile_dir: str | None = None) -> dict[str, object]:
    errors: list[str] = []
    escaped_target = (target or "about:blank").replace("'", "''")
    escaped_profile_dir = str(profile_dir or "").replace("'", "''")
    for executable in _resolve_executable_candidates(app_name):
        argument_list = ""
        normalized_executable = executable.lower()
        is_browser = "chrome" in normalized_executable or "msedge" in normalized_executable
        if is_browser:
            browser_args = ["'--new-window'", "'--no-first-run'"]
            if escaped_profile_dir:
                browser_args.append(f"'--user-data-dir={escaped_profile_dir}'")
            browser_args.append(f"'{escaped_target}'")
            argument_list = f" -ArgumentList {','.join(browser_args)}"
        elif target:
            argument_list = f" -ArgumentList '{escaped_target}'"

        proc_name = Path(executable).stem.replace("'", "''")
        if is_browser and target:
            ps_command = f"""
$ErrorActionPreference = 'Stop'
Start-Process -FilePath '{executable}'{argument_list}
"""
        else:
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
    [FocusCore]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null
    [FocusCore]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
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
                "profile_dir": profile_dir,
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


def _create_excel_workbook(
    *,
    file_name: str = "Excel-Workbook.xlsx",
    destination_location: str = "desktop",
) -> dict[str, object]:
    target_dir = location_to_path(destination_location).expanduser().resolve()
    safe_name = _sanitize_excel_file_name(file_name)
    target_path = target_dir / safe_name
    counter = 1
    while target_path.exists():
        stem = Path(safe_name).stem
        target_path = target_dir / f"{stem} ({counter}).xlsx"
        counter += 1

    ps_command = f"""
$ErrorActionPreference = 'Stop'
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$workbook = $excel.Workbooks.Add()
$workbook.SaveAs('{str(target_path).replace("'", "''")}')
$workbook.Close($true)
$excel.Quit()
[pscustomobject]@{{
    path = '{str(target_path).replace("'", "''")}'
    name = '{target_path.name.replace("'", "''")}'
    created = $true
}} | ConvertTo-Json -Depth 3
""".strip()
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
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Excel calisma kitabi olusturulamadi.")
    parsed = json.loads(completed.stdout.strip() or "{}")
    if not isinstance(parsed, dict):
        raise RuntimeError("Excel workbook olusturma yaniti gecersiz.")
    return parsed


def _write_excel_cells(*, file_path: str, cells: list[dict[str, str]]) -> dict[str, object]:
    if not cells:
        raise ValueError("write_excel_cells icin en az bir hucre gerekli.")
    payload = json.dumps(cells, ensure_ascii=False).replace("'", "''")
    ps_command = f"""
$ErrorActionPreference = 'Stop'
$cells = ConvertFrom-Json @'
{payload}
'@
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$workbook = $excel.Workbooks.Open('{file_path.replace("'", "''")}')
$sheet = $workbook.Worksheets.Item(1)
foreach ($cell in $cells) {{
    $sheet.Range($cell.cell).Value2 = $cell.value
}}
$workbook.Save()
$workbook.Close($true)
$excel.Quit()
[pscustomobject]@{{
    path = '{file_path.replace("'", "''")}'
    updated_cells = $cells.Count
}} | ConvertTo-Json -Depth 3
""".strip()
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
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Excel hucreleri yazilamadi.")
    parsed = json.loads(completed.stdout.strip() or "{}")
    if not isinstance(parsed, dict):
        raise RuntimeError("Excel hucre yazma yaniti gecersiz.")
    parsed["cells"] = cells
    return parsed


def _save_excel_workbook(*, file_path: str) -> dict[str, object]:
    target = Path(file_path).expanduser().resolve()
    if not target.exists():
        raise ValueError(f"Excel dosyasi bulunamadi: {target}")
    return {"path": str(target), "name": target.name, "saved": True}


def _resolve_ref_value(ref_key: str, context: dict[str, Any]) -> Any:
    parts = ref_key.split(".")
    target: Any = context
    traversed: list[str] = []
    for part in parts:
        traversed.append(part)
        if isinstance(target, dict):
            if part not in target:
                raise KeyError(f"$ref cozumlenemedi: {'.'.join(traversed)}")
            target = target[part]
        elif isinstance(target, list) and part.isdigit():
            idx = int(part)
            if idx >= len(target):
                raise IndexError(f"$ref liste indexi gecersiz: {ref_key}")
            target = target[idx]
        else:
            raise KeyError(f"$ref cozumlenemedi: {ref_key}")
    return target


def _resolve_refs(value: Any, context: dict[str, Any]) -> Any:
    """Step args icindeki $ref:key degerlerini context'ten recursive cozumler."""
    if isinstance(value, str) and value.startswith("$ref:"):
        return _resolve_ref_value(value[5:], context)
    if isinstance(value, dict):
        return {key: _resolve_refs(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_refs(item, context) for item in value]
    return value


def _verify_tool_result(tool_name: str, result: dict[str, Any]) -> tuple[bool, str]:
    def _path_exists(key: str) -> bool:
        raw = str(result.get(key, "")).strip()
        return bool(raw) and Path(raw).expanduser().exists()

    if tool_name == "search_files":
        count = int(result.get("count", 0) or 0)
        return (count > 0, f"{count} dosya bulundu." if count > 0 else "Eslesen dosya bulunamadi.")
    if tool_name == "create_folder":
        created_folder = result.get("created_folder")
        folder_path = str(created_folder.get("path", "")).strip() if isinstance(created_folder, dict) else ""
        ok = bool(folder_path) and Path(folder_path).expanduser().is_dir()
        return (ok, "Klasor olusturuldu." if ok else "Klasor olusturma dogrulanamadi.")
    if tool_name == "copy_files_to_path":
        count = int(result.get("count", 0) or 0)
        return (count > 0, f"{count} dosya kopyalandi." if count > 0 else "Kopyalanan dosya yok.")
    if tool_name == "move_files_to_path":
        count = int(result.get("count", 0) or 0)
        return (count > 0, f"{count} dosya tasindi." if count > 0 else "Tasinan dosya yok.")
    if tool_name == "filter_by_date":
        count = int(result.get("count", 0) or 0)
        return (count > 0, f"{count} dosya filtrede kaldi." if count > 0 else "Filtre sonrasi dosya kalmadi.")
    if tool_name == "zip_folder":
        ok = _path_exists("zip_path")
        return (ok, "Zip dosyasi olusturuldu." if ok else "Zip dosyasi olusturma dogrulanamadi.")
    if tool_name in {"send_file_by_path", "send_file"}:
        ok = str(result.get("status", "")).strip().lower() == "sent"
        return (ok, "Dosya gonderildi." if ok else "Dosya gonderimi dogrulanamadi.")
    if tool_name == "open_application":
        ok = int(result.get("returncode", 1) or 1) == 0
        return (ok, "Uygulama acildi veya one getirildi." if ok else "Uygulama acma dogrulanamadi.")
    if tool_name == "wait_for_window":
        ok = bool(result.get("found"))
        return (ok, "Beklenen pencere bulundu." if ok else "Beklenen pencere bulunamadi.")
    if tool_name == "focus_window":
        ok = bool(result.get("focused"))
        return (ok, "Pencere odaklandi." if ok else "Pencere odaklama dogrulanamadi.")
    if tool_name == "click_ui":
        ok = bool(result.get("clicked"))
        return (ok, "UI hedefi tiklandi." if ok else "UI tiklama dogrulanamadi.")
    if tool_name == "send_keys":
        ok = bool(str(result.get("keys", "")).strip())
        return (ok, "Klavye girdisi gonderildi." if ok else "Klavye girdisi bos.")
    if tool_name == "take_screenshot":
        ok = _path_exists("path")
        return (ok, "Ekran goruntusu alindi." if ok else "Screenshot dosyasi bulunamadi.")
    if tool_name == "read_screen":
        screenshot = result.get("screenshot")
        shot_path = str(screenshot.get("path", "")).strip() if isinstance(screenshot, dict) else ""
        visible_windows = result.get("visible_windows")
        ok = (bool(shot_path) and Path(shot_path).expanduser().exists()) or isinstance(visible_windows, list)
        return (ok, "Ekran durumu toplandi." if ok else "Ekran durumu dogrulanamadi.")
    if tool_name == "create_excel_workbook":
        ok = _path_exists("path")
        return (ok, "Excel calisma kitabi olusturuldu." if ok else "Excel workbook dosyasi bulunamadi.")
    if tool_name == "write_excel_cells":
        updated_cells = int(result.get("updated_cells", 0) or 0)
        ok = _path_exists("path") and updated_cells > 0
        return (ok, f"{updated_cells} hucre yazildi." if ok else "Excel hucre yazimi dogrulanamadi.")
    if tool_name == "save_excel_workbook":
        ok = bool(result.get("saved")) and _path_exists("path")
        return (ok, "Excel dosyasi kaydedildi." if ok else "Excel kaydetme dogrulanamadi.")
    return (True, "Adim tamamlandi.")


def _execute_tool_chain(steps: list[dict[str, Any]], summary: str = "") -> dict[str, object]:
    """Her step'in ciktisini context'e yazar, sonraki step $ref ile erisir."""
    context: dict[str, Any] = {
        "known_paths": {
            "desktop": str(location_to_path("desktop").expanduser().resolve()),
            "documents": str(location_to_path("documents").expanduser().resolve()),
            "downloads": str(location_to_path("downloads").expanduser().resolve()),
        }
    }
    results: list[dict[str, object]] = []
    failed_step: dict[str, object] | None = None
    blocked_step: dict[str, object] | None = None
    verified_step_count = 0

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise RuntimeError(f"Gemini tool step {i} gecersiz.")

        # $ref cozumleme
        raw_args = step.get("args") or {}
        try:
            resolved_args = cast(dict[str, Any], _resolve_refs(raw_args, context))
            resolved_step = {**step, "args": resolved_args}
            result = _execute_tool_step(resolved_step)
        except Exception as exc:
            failed_step = {
                "tool": step.get("tool", "unknown"),
                "status": "error",
                "error": str(exc),
                "step_index": i,
                "args": raw_args,
            }
            results.append(failed_step)
            break

        tool_name = str(step.get("tool", "unknown"))
        verified, verification_message = _verify_tool_result(tool_name, result)
        result["verified"] = verified
        result["verification"] = verification_message
        result["step_index"] = i
        if not verified:
            result["status"] = "blocked"
            blocked_step = {
                "tool": tool_name,
                "status": "blocked",
                "verification": verification_message,
                "step_index": i,
                "args": raw_args,
            }
            results.append(result)
            break

        result["status"] = "success"
        results.append(result)
        verified_step_count += 1

        # Context'e kaydet
        context[f"{tool_name}_result"] = result

        # Kisa erisim anahtarlari
        if isinstance(result.get("created_folder"), dict):
            context["last_folder_path"] = result["created_folder"]["path"]
        if "items" in result:
            context["last_items"] = result["items"]
        if "zip_path" in result:
            context["last_zip_path"] = result["zip_path"]
            context["last_path"] = result["zip_path"]
        if "copied_files" in result:
            context["last_items"] = result["copied_files"]
        if "moved_files" in result:
            context["last_items"] = result["moved_files"]
        if isinstance(result.get("filtered"), list):
            context["last_items"] = result["filtered"]
        if "path" in result and tool_name not in {"take_screenshot", "read_screen"}:
            context["last_path"] = result["path"]

    return {
        "summary": summary or ("Tool zinciri tamamlandi." if failed_step is None and blocked_step is None else "Tool zinciri durduruldu."),
        "steps": results,
        "step_count": len(results),
        "verified_step_count": verified_step_count,
        "success": failed_step is None and blocked_step is None,
        "failed_step": failed_step,
        "blocked_step": blocked_step,
        "context_keys": sorted(context.keys()),
    }


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
        return read_screen(
            save_name=str(args.get("save_name", "")).strip() or None,
            mode=str(args.get("mode", "")).strip() or None,
        )
    if tool == "run_powershell":
        script = str(args.get("script", "")).strip()
        if not script:
            raise ValueError("run_powershell icin script gerekli.")
        return _run_powershell_script(script, summary="Generated script executed.")
    if tool == "copy_files_to_path":
        file_paths_raw = args.get("file_paths", [])
        if isinstance(file_paths_raw, list) and file_paths_raw and isinstance(file_paths_raw[0], dict):
            file_paths_raw = [str(item.get("path", "")) for item in file_paths_raw if item.get("path")]
        destination_path = str(args.get("destination_path", "")).strip()
        if not file_paths_raw or not destination_path:
            raise ValueError("copy_files_to_path icin file_paths ve destination_path gerekli.")
        copied = copy_files_to_path(list(file_paths_raw), destination_path, allowed_folders=settings.allowed_folders)
        if not copied:
            raise ValueError("Kopyalanacak gecerli dosya bulunamadi.")
        return {"tool": "copy_files_to_path", "copied_files": copied, "count": len(copied), "destination": destination_path}
    if tool == "move_files_to_path":
        file_paths_raw = args.get("file_paths", [])
        if isinstance(file_paths_raw, list) and file_paths_raw and isinstance(file_paths_raw[0], dict):
            file_paths_raw = [str(item.get("path", "")) for item in file_paths_raw if item.get("path")]
        destination_path = str(args.get("destination_path", "")).strip()
        if not file_paths_raw or not destination_path:
            raise ValueError("move_files_to_path icin file_paths ve destination_path gerekli.")
        moved = move_files_to_path(list(file_paths_raw), destination_path, allowed_folders=settings.allowed_folders)
        if not moved:
            raise ValueError("Tasinacak gecerli dosya bulunamadi.")
        return {"tool": "move_files_to_path", "moved_files": moved, "count": len(moved), "destination": destination_path}
    if tool == "zip_folder":
        folder_path = str(args.get("folder_path", "")).strip()
        if not folder_path:
            raise ValueError("zip_folder icin folder_path gerekli.")
        output_name = str(args.get("output_name", "")).strip() or None
        result = zip_directory(folder_path, output_name, allowed_folders=settings.allowed_folders)
        return {"tool": "zip_folder", **result}
    if tool == "filter_by_date":
        files_raw = args.get("files", [])
        if not isinstance(files_raw, list):
            files_raw = []
        month = args.get("month")
        year = args.get("year")
        filtered = filter_files_by_date(
            files_raw,
            month=int(month) if month is not None else None,
            year=int(year) if year is not None else None,
        )
        return {"tool": "filter_by_date", "filtered": filtered, "items": filtered, "count": len(filtered)}
    if tool == "send_file_by_path":
        file_path = str(args.get("file_path", "")).strip()
        recipient = str(args.get("recipient", "")).strip()
        if not file_path:
            raise ValueError("send_file_by_path icin file_path gerekli.")
        if not recipient:
            raise ValueError("send_file_by_path icin recipient gerekli.")
        from core.config import add_mail_recipient_to_whitelist
        settings.mail_recipients_whitelist = add_mail_recipient_to_whitelist(recipient)
        send_email_with_attachment(
            recipient=recipient,
            subject="AI Destekli Teknik Destek Ajani",
            body="Istenen dosya ektedir.",
            file_path=file_path,
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
        return {"tool": "send_file_by_path", "file_path": file_path, "recipient": recipient, "status": "sent"}
    if tool == "create_excel_workbook":
        created = _create_excel_workbook(
            file_name=str(args.get("file_name", "")).strip() or "Excel-Workbook.xlsx",
            destination_location=str(args.get("destination_location", "desktop")).strip() or "desktop",
        )
        return {"tool": "create_excel_workbook", **created}
    if tool == "write_excel_cells":
        file_path = str(args.get("file_path", "")).strip()
        cells = args.get("cells", [])
        if not file_path:
            raise ValueError("write_excel_cells icin file_path gerekli.")
        if not isinstance(cells, list):
            raise ValueError("write_excel_cells icin cells listesi gerekli.")
        normalized_cells = [
            {"cell": str(item.get("cell", "")).strip(), "value": str(item.get("value", ""))}
            for item in cells
            if isinstance(item, dict) and str(item.get("cell", "")).strip()
        ]
        updated = _write_excel_cells(file_path=file_path, cells=normalized_cells)
        return {"tool": "write_excel_cells", **updated}
    if tool == "save_excel_workbook":
        file_path = str(args.get("file_path", "")).strip()
        if not file_path:
            raise ValueError("save_excel_workbook icin file_path gerekli.")
        saved = _save_excel_workbook(file_path=file_path)
        return {"tool": "save_excel_workbook", **saved}
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


def _process_name_from_open_result(context: dict[str, object], fallback: str) -> str:
    opened_with = str(context.get("opened_with", "")).strip().lower()
    if opened_with:
        stem = Path(opened_with).stem.lower()
        if stem:
            return stem
    return fallback


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


def _looks_like_excel_sheet_edit_workflow(instruction: str) -> bool:
    normalized = instruction.lower()
    has_excel = any(token in normalized for token in ("excel", "calisma kitabi", "çalışma kitabı", "sutun", "sütun", "hucres", "hücres"))
    has_edit = any(token in normalized for token in ("yaz", "kaydet", "baslik", "başlık", "ac", "aç"))
    return has_excel and has_edit


def _extract_excel_cells(instruction: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"([A-Za-z])\s*(?:1\s*)?(?:sutununa|sütununa|sutun basligina|sütun başlığına|hucresine|hücresine)\s+(.+?)(?=(?:\s+[A-Za-z]\s*(?:1\s*)?(?:sutununa|sütununa|sutun basligina|sütun başlığına|hucresine|hücresine))|\s+yaz|\s+kaydet|$)",
        flags=re.IGNORECASE,
    )
    cells: list[dict[str, str]] = []
    for column, value in pattern.findall(instruction):
        cleaned_value = value.strip(" .,:;")
        cleaned_value = re.sub(r"^(?:baslik olarak|başlık olarak)\s+", "", cleaned_value, flags=re.IGNORECASE)
        if cleaned_value:
            cells.append({"cell": f"{column.upper()}1", "value": cleaned_value})
    if not cells:
        raise RuntimeError("Excel hucre degerleri cikartilamadi.")
    return cells


def _excel_sheet_edit_workflow(instruction: str) -> dict[str, object]:
    cells = _extract_excel_cells(instruction)
    file_name = "Excel-Workbook.xlsx"
    execution = _execute_tool_chain(
        [
            {"tool": "create_excel_workbook", "args": {"file_name": file_name, "destination_location": "desktop"}},
            {"tool": "write_excel_cells", "args": {"file_path": "$ref:last_path", "cells": cells}},
            {"tool": "save_excel_workbook", "args": {"file_path": "$ref:last_path"}},
        ],
        summary="Excel calisma kitabi tool zinciri ile duzenlendi.",
    )
    execution["cells"] = cells
    return execution


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
    profile_dir = str((BASE_DIR / str(settings.playwright_user_data_dir)).resolve())
    execution = execute_workflow(
        summary="Mail oturumu icin hazirlama zinciri calistirildi.",
        initial_context={},
        steps=[
            WorkflowStep(
                id="open_mail",
                title="Mail penceresini ac",
                run=lambda context: _open_application(
                    app_name=browser_app,
                    target=settings.playwright_mail_url,
                    profile_dir=profile_dir,
                ),
            ),
            WorkflowStep(
                id="wait_window",
                title="Mail penceresinin gelmesini bekle",
                run=lambda context: wait_for_window(
                    process_name=_process_name_from_open_result(context, browser_app),
                    timeout_seconds=25,
                ),
            ),
            WorkflowStep(
                id="focus_window",
                title="Mail penceresine odaklan",
                run=lambda context: focus_window(process_name=_process_name_from_open_result(context, browser_app)),
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
    ai_provider: str = "gemini",
    workflow_profile: str | None,
    allowed_folders: Iterable[str],
    forbidden_actions: Iterable[str],
) -> dict[str, object]:
    if _looks_like_python_command_repair(instruction):
        return _repair_python_command_resolution()
    if _looks_like_excel_sheet_edit_workflow(instruction):
        return _excel_sheet_edit_workflow(instruction)
    if _looks_like_write_text_into_file_workflow(instruction):
        return _write_text_into_file_workflow(instruction)
    if _looks_like_folder_and_text_file_workflow(instruction):
        return _folder_and_text_file_workflow(instruction)
    if _looks_like_mail_session_workflow(instruction):
        return _mail_session_workflow()
    if _looks_like_window_guidance_workflow(instruction):
        return _window_guidance_workflow(instruction)

    prompt = _build_generation_prompt(
        instruction,
        workflow_profile=workflow_profile,
        allowed_folders=allowed_folders,
        forbidden_actions=forbidden_actions,
    )

    if ai_provider == "openrouter":
        payload = generate_powershell_script_with_openrouter(
            api_key=api_key,
            model=model,
            prompt=prompt,
        )
    else:
        payload = generate_powershell_script_with_gemini(
            api_key=api_key,
            model=model,
            prompt=prompt,
        )
    summary = str(payload.get("summary", "")).strip()
    steps = payload.get("steps")
    if isinstance(steps, list) and steps:
        return _execute_tool_chain(steps, summary=summary or "Tool plan executed.")

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
