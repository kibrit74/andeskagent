"""TeknikAjan MCP Tool Server.

Mevcut adapter fonksiyonlarini MCP toollari olarak expose eder.
Claude Code CLI bu sunucuyu stdio uzerinden kullanarak
masaustu otomasyonu, dosya islemleri ve sistem yonetimi yapabilir.

Kullanim:
    python tools/mcp_server.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

# Proje kokunu Python path'ine ekle
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from core.config import AppSettings, load_settings  # noqa: E402

# ---------------------------------------------------------------------------
# MCP Server baslat
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "teknikajan",
    instructions=(
        "Sen bir Windows uzaktan teknik destek ajanisin. "
        "Bu sunucu yerel Windows makinesinde dosya islemleri, "
        "masaustu otomasyonu, mail gonderimi ve sistem yonetimi "
        "toollari saglar. Kullanici Turkce konusur, yanitlarin "
        "Turkce olmalidir."
    ),
)

# ---------------------------------------------------------------------------
# Ayarlari yukle (her cagri icin taze)
# ---------------------------------------------------------------------------

def _settings() -> AppSettings:
    return load_settings()


def _json_result(data: Any) -> str:
    """Tool sonucunu JSON string olarak dondurur."""
    if isinstance(data, str):
        return data
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _selected_path(selected: dict[str, object]) -> str:
    path = selected.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Secilen dosya sonucu path alani icermiyor.")
    return path


# =========================================================================
# DOSYA ISLEMLERI
# =========================================================================

@mcp.tool()
def search_files(
    query: str = "",
    location: str = "desktop",
    extension: str | None = None,
) -> str:
    """Belirtilen konumda dosya arar.

    Args:
        query: Aranacak dosya adi veya anahtar kelime. Bos birakabilirsiniz.
        location: Arama konumu - desktop, documents veya downloads
        extension: Dosya uzantisi filtresi (ornegin xlsx, pdf, docx). Noktasiz yazin.
    """
    from adapters.file_adapter import search_files as _search

    settings = _settings()
    items = _search(query, location, extension, allowed_folders=settings.allowed_folders)
    return _json_result({"items": items, "count": len(items)})


@mcp.tool()
def open_file(
    query: str,
    location: str = "desktop",
    extension: str | None = None,
) -> str:
    """Dosyayi bulup varsayilan uygulamada acar.

    Args:
        query: Aranacak dosya adi veya anahtar kelime
        location: Arama konumu - desktop, documents veya downloads
        extension: Dosya uzantisi filtresi. Noktasiz yazin.
    """
    from adapters.file_adapter import open_file_path, search_files as _search

    settings = _settings()
    items = _search(query, location, extension, allowed_folders=settings.allowed_folders)
    if not items:
        return _json_result({"error": "Eslesen dosya bulunamadi.", "query": query})
    selected = max(items, key=lambda x: x.get("modified_at", 0))
    result = open_file_path(_selected_path(selected), allowed_folders=settings.allowed_folders)
    return _json_result(result)


@mcp.tool()
def copy_file(
    query: str,
    location: str = "desktop",
    destination_location: str = "desktop",
    extension: str | None = None,
) -> str:
    """Dosyayi bulup belirtilen konuma kopyalar.

    Args:
        query: Kaynak dosya adi veya anahtar kelime
        location: Kaynak konum - desktop, documents veya downloads
        destination_location: Hedef konum - desktop, documents veya downloads
        extension: Dosya uzantisi filtresi. Noktasiz yazin.
    """
    from adapters.file_adapter import copy_file_to_location, search_files as _search

    settings = _settings()
    items = _search(query, location, extension, allowed_folders=settings.allowed_folders)
    if not items:
        return _json_result({"error": "Kopyalanacak dosya bulunamadi."})
    selected = max(items, key=lambda x: x.get("modified_at", 0))
    copied = copy_file_to_location(
        _selected_path(selected),
        destination_location=destination_location,
        allowed_folders=settings.allowed_folders,
    )
    return _json_result({"source": selected, "copied": copied})


@mcp.tool()
def move_file(
    query: str,
    location: str = "desktop",
    destination_location: str = "desktop",
    extension: str | None = None,
) -> str:
    """Dosyayi bulup belirtilen konuma tasir.

    Args:
        query: Kaynak dosya adi veya anahtar kelime
        location: Kaynak konum - desktop, documents veya downloads
        destination_location: Hedef konum - desktop, documents veya downloads
        extension: Dosya uzantisi filtresi. Noktasiz yazin.
    """
    from adapters.file_adapter import move_file_to_location, search_files as _search

    settings = _settings()
    items = _search(query, location, extension, allowed_folders=settings.allowed_folders)
    if not items:
        return _json_result({"error": "Tasinacak dosya bulunamadi."})
    selected = max(items, key=lambda x: x.get("modified_at", 0))
    moved = move_file_to_location(
        _selected_path(selected),
        destination_location=destination_location,
        allowed_folders=settings.allowed_folders,
    )
    return _json_result({"source": selected, "moved": moved})


@mcp.tool()
def rename_file(
    query: str,
    new_name: str,
    location: str = "desktop",
    extension: str | None = None,
) -> str:
    """Dosyayi bulup yeniden adlandirir.

    Args:
        query: Yeniden adlandirilacak dosya adi veya anahtar kelime
        new_name: Yeni dosya adi
        location: Arama konumu - desktop, documents veya downloads
        extension: Dosya uzantisi filtresi. Noktasiz yazin.
    """
    from adapters.file_adapter import rename_file_in_place, search_files as _search

    settings = _settings()
    items = _search(query, location, extension, allowed_folders=settings.allowed_folders)
    if not items:
        return _json_result({"error": "Yeniden adlandirilacak dosya bulunamadi."})
    selected = max(items, key=lambda x: x.get("modified_at", 0))
    renamed = rename_file_in_place(
        _selected_path(selected),
        new_name=new_name,
        allowed_folders=settings.allowed_folders,
    )
    return _json_result({"source": selected, "renamed": renamed})


@mcp.tool()
def delete_file(
    query: str,
    location: str = "desktop",
    extension: str | None = None,
) -> str:
    """Dosyayi bulup siler. DIKKAT: Bu islem geri alinamaz.

    Args:
        query: Silinecek dosya adi veya anahtar kelime
        location: Arama konumu - desktop, documents veya downloads
        extension: Dosya uzantisi filtresi. Noktasiz yazin.
    """
    from adapters.file_adapter import delete_file_in_place, search_files as _search

    settings = _settings()
    items = _search(query, location, extension, allowed_folders=settings.allowed_folders)
    if not items:
        return _json_result({"error": "Silinecek dosya bulunamadi."})
    selected = max(items, key=lambda x: x.get("modified_at", 0))
    deleted = delete_file_in_place(
        _selected_path(selected),
        allowed_folders=settings.allowed_folders,
    )
    return _json_result({"deleted": deleted})


@mcp.tool()
def create_folder(
    folder_name: str = "Yeni Klasor",
    destination_location: str = "desktop",
) -> str:
    """Belirtilen konumda yeni klasor olusturur.

    Args:
        folder_name: Olusturulacak klasorun adi
        destination_location: Konum - desktop, documents veya downloads
    """
    from adapters.file_adapter import create_folder_in_location

    settings = _settings()
    created = create_folder_in_location(
        folder_name,
        destination_location=destination_location,
        allowed_folders=settings.allowed_folders,
    )
    return _json_result({"created_folder": created})


# =========================================================================
# AGENT BROWSER / WEB
# =========================================================================

def _web_search_url(query: str, engine: str = "duckduckgo") -> str:
    cleaned_query = (query or "").strip()
    normalized_engine = (engine or "duckduckgo").strip().lower()
    base_url = "https://www.google.com/search?q=" if normalized_engine == "google" else "https://duckduckgo.com/?q="
    if not cleaned_query:
        return "https://www.google.com/" if normalized_engine == "google" else "https://duckduckgo.com/"
    return f"{base_url}{quote_plus(cleaned_query)}"


@mcp.tool()
def open_agent_browser(target_url: str | None = None) -> str:
    """Playwright tabanli agent tarayiciyi acar.

    Normal Chrome acmak icin degil, agent'in kontrol edecegi web oturumu icin kullanilir.
    Tarayicidan/webden/siteye git isteklerinde open_application yerine bunu kullanin.

    Args:
        target_url: Opsiyonel hedef URL. Bos ise sadece agent tarayici oturumu acilir.
    """
    from adapters.agent_browser_adapter import open_agent_browser_session

    session = open_agent_browser_session(target_url=target_url)
    return _json_result({
        "session_id": session.session_id,
        "title": session.title,
        "url": session.url,
        "page_count": session.page_count,
        "mode": session.mode,
        "reused": session.reused,
        "opened": session.opened,
        "loaded": session.loaded,
    })


@mcp.tool()
def navigate_agent_browser(url: str) -> str:
    """Agent tarayici icinde verilen URL'ye gider.

    Gmail, Google, web sitesi, PDF linki veya herhangi bir web adresine gitmek icin kullanilir.
    Normal Chrome acmaz; mevcut Playwright agent tarayici oturumunu kullanir.

    Args:
        url: Gidilecek URL.
    """
    from adapters.agent_browser_adapter import navigate_agent_browser as _navigate

    session = _navigate(url)
    return _json_result({
        "session_id": session.session_id,
        "title": session.title,
        "url": session.url,
        "page_count": session.page_count,
        "mode": session.mode,
        "reused": session.reused,
        "opened": session.opened,
        "loaded": session.loaded,
    })


@mcp.tool()
def search_web(query: str, engine: str = "duckduckgo") -> str:
    """Agent tarayici ile Google web aramasi yapar.

    Kullanici 'Google'da ara', 'webde ara', 'tarayicidan ... ara' dediginde bu tool'u kullanin.
    Yerel dosya aramasi icin search_files kullanilir; web aramasi icin search_web kullanilir.
    Varsayilan arama motoru DuckDuckGo'dur; Google Playwright/otomasyon oturumunu CAPTCHA'ya dusurebilir.

    Args:
        query: Google'da aranacak ifade. PDF isteniyorsa sorguya pdf veya filetype:pdf eklenebilir.
        engine: duckduckgo veya google. Varsayilan duckduckgo.
    """
    from adapters.agent_browser_adapter import navigate_agent_browser as _navigate

    url = _web_search_url(query, engine)
    session = _navigate(url)
    return _json_result({
        "query": query,
        "engine": engine,
        "search_url": url,
        "session_id": session.session_id,
        "title": session.title,
        "url": session.url,
        "page_count": session.page_count,
        "mode": session.mode,
        "reused": session.reused,
        "opened": session.opened,
        "loaded": session.loaded,
    })


# =========================================================================
# MASAUSTU OTOMASYONU
# =========================================================================

@mcp.tool()
def open_application(
    app_name: str,
    target: str | None = None,
) -> str:
    """Bir uygulamayi acar veya zaten aciksa one getirir.

    Args:
        app_name: Uygulama adi - chrome, outlook, excel, word, notepad, calculator, paint, explorer gibi
        target: Opsiyonel URL veya dosya yolu. Chrome/Edge icin URL acabilir.
    """
    from adapters.script_adapter import _open_application

    result = _open_application(app_name=app_name, target=target)
    return _json_result(result)


@mcp.tool()
def list_windows() -> str:
    """Gorunen tum acik pencereleri listeler. Pencere adi, islem adi ve ID bilgisi doner."""
    from adapters.desktop_adapter import list_windows as _list_windows

    result = _list_windows()
    return _json_result(result)


@mcp.tool()
def focus_window(
    title_contains: str | None = None,
    process_name: str | None = None,
) -> str:
    """Belirtilen pencereyi one getirir ve odaklar.

    Args:
        title_contains: Pencere basliginda geçen metin
        process_name: Islem adi (ornegin outlook, chrome, excel)
    """
    from adapters.desktop_adapter import focus_window as _focus_window

    result = _focus_window(
        title_contains=title_contains,
        process_name=process_name,
    )
    return _json_result(result)


@mcp.tool()
def wait_for_window(
    title_contains: str | None = None,
    process_name: str | None = None,
    timeout_seconds: int = 20,
) -> str:
    """Belirtilen pencerenin acilmasini bekler.

    Args:
        title_contains: Beklenen pencere basliginda geçen metin
        process_name: Beklenen islem adi
        timeout_seconds: Maksimum bekleme suresi (saniye). Varsayilan 20.
    """
    from adapters.desktop_adapter import wait_for_window as _wait_for_window

    result = _wait_for_window(
        title_contains=title_contains,
        process_name=process_name,
        timeout_seconds=timeout_seconds,
    )
    return _json_result(result)


@mcp.tool()
def click_ui(
    text: str | None = None,
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    title_contains: str | None = None,
    process_name: str | None = None,
) -> str:
    """Arayuzde bir hedef UI elemanina tiklar. Metin veya koordinat ile hedef belirleyebilirsiniz.

    Args:
        text: UI elemanindaki metin (ornegin buton adi). Koordinat yoksa zorunlu.
        x: Tiklanacak X koordinati
        y: Tiklanacak Y koordinati
        button: Mouse butonu - left veya right
        title_contains: Hedef pencere basliginda geçen metin
        process_name: Hedef islem adi (ornegin outlook, chrome)
    """
    from adapters.desktop_adapter import click_ui as _click_ui

    result = _click_ui(
        text=text,
        x=x,
        y=y,
        button=button,
        title_contains=title_contains,
        process_name=process_name,
    )
    return _json_result(result)


@mcp.tool()
def type_ui(
    text_to_type: str,
    text_filter: str | None = None,
    title_contains: str | None = None,
    process_name: str | None = None,
) -> str:
    """Bir UI alanina yazi yazar. Oncellikle text_filter ile alana tiklar, sonra yazi gonderir.

    Args:
        text_to_type: Yazilacak metin
        text_filter: Hedef UI alaninin ekrandaki adi (ornegin 'Kime', 'Konu'). Varsa once bu alana tiklar.
        title_contains: Hedef pencere basliginda geçen metin
        process_name: Hedef islem adi
    """
    from adapters.desktop_adapter import type_ui as _type_ui

    result = _type_ui(
        text_to_type=text_to_type,
        text_filter=text_filter,
        title_contains=title_contains,
        process_name=process_name,
    )
    return _json_result(result)


@mcp.tool()
def read_screen(mode: str = "medium") -> str:
    """Ekranin guncel durumunu okur - acik pencereler, screenshot ve opsiyonel OCR.

    Args:
        mode: Okuma derinligi - fast (sadece pencereler), medium (pencereler + screenshot), full (pencereler + screenshot + UIAutomation + OCR)
    """
    from adapters.desktop_adapter import read_screen as _read_screen

    result = _read_screen(mode=mode)
    # Screenshot binary verisini cikar, dosya yolu yeterli
    if isinstance(result, dict) and "screenshot" in result:
        screenshot = result.get("screenshot")
        if isinstance(screenshot, dict):
            result["screenshot_path"] = screenshot.get("path")
        result.pop("screenshot", None)
    return _json_result(result)


@mcp.tool()
def take_screenshot() -> str:
    """Ekranin tam goruntusu alinir ve dosya yolu dondurulur."""
    from adapters.desktop_adapter import take_screenshot as _take_screenshot

    result = _take_screenshot()
    return _json_result(result)


@mcp.tool()
def send_keys(keys: str, press_enter: bool = False) -> str:
    """Aktif pencereye klavye girdisi gonderir. Metin yazma veya ozel tuslar icin kullanilir.

    Args:
        keys: Gonderilecek metin veya tus dizisi
        press_enter: True ise metnin sonunda Enter tusuna basilir
    """
    from adapters.script_adapter import _send_keys

    result = _send_keys(keys=keys, press_enter=press_enter)
    return _json_result(result)


# =========================================================================
# MAIL
# =========================================================================

@mcp.tool()
def send_email(
    recipient: str,
    file_query: str = "",
    location: str = "desktop",
    extension: str | None = None,
    subject: str = "AI Destekli Teknik Destek Ajani",
    body: str = "Istenen dosya ektedir.",
) -> str:
    """Dosya arayip bulur ve e-posta olarak gonderir.

    Args:
        recipient: Alici e-posta adresi
        file_query: Gonderilecek dosyanin adi veya anahtar kelimesi
        location: Dosya arama konumu - desktop, documents veya downloads
        extension: Dosya uzantisi filtresi. Noktasiz yazin.
        subject: E-posta konusu
        body: E-posta metni
    """
    from adapters.file_adapter import search_files as _search
    from adapters.mail_adapter import send_email_with_attachment

    settings = _settings()
    items = _search(file_query, location, extension, allowed_folders=settings.allowed_folders)
    if not items:
        return _json_result({"error": "Gonderilecek dosya bulunamadi.", "query": file_query})
    selected = max(items, key=lambda x: x.get("modified_at", 0))

    send_email_with_attachment(
        recipient=recipient,
        subject=subject,
        body=body,
        file_path=_selected_path(selected),
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
        sender=settings.default_mail_from,
        allowed_recipients=getattr(settings, "mail_recipients_whitelist", []),
        mail_transport=settings.mail_transport,
        browser_channel=settings.playwright_browser_channel,
        user_data_dir=settings.playwright_user_data_dir,
        mail_url=settings.playwright_mail_url,
        headless=settings.playwright_headless,
    )
    return _json_result({
        "status": "sent",
        "file": selected,
        "recipient": recipient,
    })


# =========================================================================
# SCRIPT & SISTEM
# =========================================================================

@mcp.tool()
def list_scripts() -> str:
    """Calistirilabilir whitelisted PowerShell scriptlerini listeler."""
    from adapters.script_adapter import ScriptAdapter

    settings = _settings()
    adapter = ScriptAdapter(allowed_scripts=settings.allowed_scripts)
    items = adapter.list_scripts()
    return _json_result({"items": items, "count": len(items)})


@mcp.tool()
def run_script(script_name: str) -> str:
    """Whitelisted bir PowerShell scriptini calistirir.

    Args:
        script_name: Manifest dosyasindaki script adi
    """
    from adapters.script_adapter import ScriptAdapter

    settings = _settings()
    adapter = ScriptAdapter(allowed_scripts=settings.allowed_scripts)
    result = adapter.run(script_name)
    return _json_result({
        "script": result.script,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    })


@mcp.tool()
def get_system_status() -> str:
    """Sistem durumunu ve kaynak kullanimini (CPU, RAM, disk) raporlar."""
    from adapters.system_adapter import get_system_status as _get_system_status

    result = _get_system_status()
    return _json_result(result)


@mcp.tool()
def run_powershell(script: str) -> str:
    """Guvenli bir PowerShell komutu calistirir. Silme, formatlama, registry degistirme, shutdown YASAKTIR.

    Args:
        script: Calistirilacak PowerShell scripti. Tek basina calisabilir olmali.
    """
    from adapters.script_adapter import _run_powershell_script

    result = _run_powershell_script(script, summary="MCP uzerinden calistirilan PowerShell")
    return _json_result(result)


@mcp.tool()
def create_ticket(
    title: str,
    description: str = "",
) -> str:
    """Destek bileti olusturur.

    Args:
        title: Bilet basligi
        description: Bilet aciklamasi
    """
    from db import create_support_ticket

    settings = _settings()
    ticket_id = create_support_ticket(
        settings.sqlite_path,
        title=title,
        description=description,
        source_text=description,
        metadata={},
    )
    return _json_result({
        "ticket_id": ticket_id,
        "status": "created",
        "title": title,
    })


# =========================================================================
# Sunucu Baslat
# =========================================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")
