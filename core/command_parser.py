"""Dogal dil komutlarini API aksiyonlarina donusturen parser."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from adapters.gemini_adapter import parse_command_with_gemini
from adapters.openrouter_adapter import parse_command_with_openrouter
from core.config import AppSettings, load_settings
from core.knowledge import KnowledgeService

knowledge_service = KnowledgeService()

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_CONTEXT_PATH = BASE_DIR / ".teknikajan.md"

ALLOWED_ACTIONS = (
    "search_file",
    "open_file",
    "copy_file",
    "move_file",
    "rename_file",
    "delete_file",
    "create_folder",
    "send_file",
    "send_latest",
    "open_application",
    "open_agent_browser",
    "navigate_agent_browser",
    "open_document_in_agent_browser",
    "click_pdf_link",
    "list_pdf_links",
    "reuse_agent_browser_session",
    "read_agent_browser_state",
    "close_agent_browser_session",
    "list_windows",
    "focus_window",
    "wait_for_window",
    "click_ui",
    "type_ui",
    "verify_ui_state",
    "read_screen",
    "take_screenshot",
    "create_ticket",
    "run_script",
    "system_status",
    "list_scripts",
    "unknown",
)

ALLOWED_LOCATIONS = ("desktop", "documents", "downloads")
WORKFLOW_PROFILES = (
    "agent_browser",
    "file_chain",
    "excel_workflow",
    "app_control",
    "screen_inspect",
    "system_repair",
    "generic",
)
MULTI_STEP_MARKERS = (" ve ", " sonra ", " ardindan ", " ardından ")


@dataclass(slots=True)
class ParsedCommand:
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    knowledge_hint: str | None = None
    workflow_profile: str | None = None


def _normalize(text: str) -> str:
    normalized = text.lower().strip().lstrip("-* ").strip()
    replacements = {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    }
    replacements.update({
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    })
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _normalize_command_text(text: str) -> str:
    normalized = text.strip()
    replacements = (
        (r"\bmasa\s+ustu\b", "masaustu"),
        (r"\bmasa\s+üstü\b", "masaüstü"),
        (r"\bmasa\s+utunde\b", "masaustunde"),
        (r"\bmasa\s+üstünde\b", "masaüstünde"),
        (r"\bmasa\s+utune\b", "masaustune"),
        (r"\bmasa\s+üstüne\b", "masaüstüne"),
        (r"\bmasa\s+utundeki\b", "masaustundeki"),
        (r"\bmasa\s+üstündeki\b", "masaüstündeki"),
        (r"\bmasa\s+ustunde\s+ki\b", "masaustundeki"),
        (r"\bmasa\s+üstünde\s+ki\b", "masaüstündeki"),
        (r"\bmasa\s+utunde\s+ki\b", "masaustundeki"),
        (r"\bmasa\s+ütünde\s+ki\b", "masaüstündeki"),
        (r"\bexceller\b", "excel"),
        (r"\bexcel ler\b", "excel"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _looks_like_multi_step_file_workflow(text: str) -> bool:
    normalized = _normalize(text)
    has_folder_creation = "klasor" in normalized and any(token in normalized for token in ("olustur", "create", "yeni"))
    has_bulk_files = any(token in normalized for token in ("tum", "hepsi", "butun", "dosyalari"))
    has_file_type = any(token in normalized for token in ("excel", "xlsx", "pdf", "csv", "txt", "word", "docx"))
    has_transfer = any(token in normalized for token in (" tasi", " tasi ", "tasin", "kopyala", "arsivle", "zip"))
    return has_folder_creation and has_bulk_files and has_file_type and has_transfer


def _looks_like_folder_archive_workflow(text: str) -> bool:
    normalized = _normalize(text)
    has_folder_target = "klasor" in normalized or "folder" in normalized
    has_archive_intent = any(token in normalized for token in ("zip", "ziple", "arsivle", "arsiv"))
    return has_folder_target and has_archive_intent


def _looks_like_excel_edit_workflow(text: str) -> bool:
    normalized = _normalize(text)
    has_excel_target = any(token in normalized for token in ("excel", "calisma kitabi", "workbook", "sutun", "hucre", "cell"))
    has_edit_intent = any(token in normalized for token in ("yaz", "doldur", "baslik", "kaydet", "ekle", "ac"))
    return has_excel_target and has_edit_intent


def _classify_agent_browser_intent(text: str) -> str | None:
    normalized = _normalize(_normalize_command_text(text))

    pdf_link_phrases = (
        "pdfdeki linke tikla",
        "pdf deki linke tikla",
        "pdf icindeki linke tikla",
        "pdf deki baglantiya tikla",
        "dokumandaki linke tikla",
        "belgedeki linke tikla",
        "sayfadaki linke tikla",
    )
    if any(phrase in normalized for phrase in pdf_link_phrases):
        return "click_pdf_link"

    if re.search(r"\bhttps?://", text, flags=re.IGNORECASE):
        return "navigate_agent_browser"

    if any(token in normalized for token in ("tarayici ac", "tarayiciyi ac", "browser ac", "browseri ac")):
        if not any(token in normalized for token in (" git", "adres", "gmail", "takvim", "calendar", "site", "url", "link")):
            return "open_agent_browser"

    site_navigation_phrases = (
        "siteye git",
        "siteyi ac",
        "web sitesini ac",
        "adrese git",
        "adresine git",
        "url ac",
        "linki ac",
        "gmail'e git",
        "gmail e git",
        "gmaili ac",
        "gmail ac",
        "gmail adresine git",
        "takvime git",
        "takvimi ac",
        "calendar ac",
        "calendari ac",
        "takvimde",
        "calendarda",
    )
    if any(phrase in normalized for phrase in site_navigation_phrases):
        return "navigate_agent_browser"

    has_document_target = any(token in normalized for token in (" pdf", "pdf ", "dokumani", "belge", "dokuman"))
    has_document_open_intent = any(
        phrase in normalized
        for phrase in (
            "bul ve ac",
            "bulup ac",
            "dosyayi ac",
            "dosyasini ac",
            "dosyasini ac",
            "dokumani ac",
            "dokumani bul ve ac",
            "pdfyi ac",
            "pdf yi ac",
            "pdf dosyasini ac",
            "pdf dosyayi ac",
        )
    )
    if has_document_target and has_document_open_intent:
        return "open_document_in_agent_browser"

    browser_followup_phrases = (
        "ayni sekmede",
        "sekmede devam et",
        "tarayicida devam et",
        "sayfada devam et",
        "webde devam et",
    )
    if any(phrase in normalized for phrase in browser_followup_phrases):
        return "reuse_agent_browser_session"

    return None


def _looks_like_agent_browser_workflow(text: str) -> bool:
    return _classify_agent_browser_intent(text) is not None


def route_to_workflow_profile(text: str) -> str:
    normalized = _normalize(_normalize_command_text(text))

    if any(token in normalized for token in ("sistem durumu", "script", "python komutu", "onar", "repair", "fix", "ticket", "bilet", "destek bileti", "destek kaydi")):
        return "system_repair"
    if _looks_like_excel_edit_workflow(text):
        return "excel_workflow"
    if _looks_like_agent_browser_workflow(text):
        return "agent_browser"
    if _looks_like_multi_step_file_workflow(text) or _looks_like_folder_archive_workflow(text):
        return "file_chain"
    if any(token in normalized for token in ("ekrani oku", "screenshot", "ekran goruntusu", "ekran resmi", "dogrula", "kontrol et")):
        return "screen_inspect"
    if any(token in normalized for token in ("outlook", "chrome", "excel", "word", "notepad", "tikla", "pencere", "odak", "bekle")):
        return "app_control"
    if any(token in normalized for token in ("dosya", "pdf", "excel", "xlsx", "csv", "gonder", "mail", "zip", "ziple", "kopyala", "tasi")):
        return "file_chain"
    return "generic"


def _match_script_aliases(text: str) -> list[str]:
    normalized = _normalize(text)
    matches: list[tuple[int, str]] = []
    for item in knowledge_service.load_script_catalog():
        best_position: int | None = None
        for alias in item["aliases"]:
            position = normalized.find(alias)
            if position >= 0 and (best_position is None or position < best_position):
                best_position = position
        if best_position is not None:
            matches.append((best_position, str(item["name"])))

    matches.sort(key=lambda entry: entry[0])
    ordered_names: list[str] = []
    for _, name in matches:
        if name not in ordered_names:
            ordered_names.append(name)
    return ordered_names


def _detect_extension(text: str) -> str | None:
    normalized = _normalize(text)
    match = re.search(r"\.(xlsx?|docx?|pdf|txt|csv|pptx?|zip|rar)", normalized)
    if match:
        return match.group(0).lstrip(".")

    ext_map = {"excel": "xlsx", "word": "docx", "pdf": "pdf", "csv": "csv", "powerpoint": "pptx"}
    for word, ext in ext_map.items():
        if word in normalized:
            return ext
    return None


def _extract_email(text: str) -> str | None:
    match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
    return match.group(0) if match else None


def _extract_url(text: str) -> str | None:
    match = re.search(r"\bhttps?://[^\s)]+", text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(0).strip().rstrip(").,;")


def _extract_ticket_summary(text: str) -> str:
    normalized = _normalize(text)
    cleaned = re.sub(r"\b(destek bileti|destek kaydi|ticket|bilet)\b", " ", normalized)
    cleaned = re.sub(r"\b(ac|olustur|create|acalim)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-")
    return cleaned[:120] if cleaned else "Destek Talebi"


def _simplify_click_target(raw_text: str, full_text: str) -> str:
    candidate = _normalize(raw_text or "")
    full_normalized = _normalize(full_text or "")

    if "link" in candidate or "link" in full_normalized:
        return "link"
    if "gonder" in candidate:
        return "Gonder"
    if "send" in candidate:
        return "Send"

    candidate = re.sub(
        r"\b(simdi|lutfen|pdf|deki|adli|isimli|dosya|dokumani|dokumani_v1|sayfanin|ustundeki|uzerindeki)\b",
        " ",
        candidate,
    )
    candidate = re.sub(r"\b(click|tikla|tiklayin|butonuna|dugmesine|bas)\b", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" .:-")
    if not candidate:
        return ""
    words = candidate.split()
    if len(words) > 3:
        candidate = " ".join(words[-3:])
    if len(candidate) > 32:
        candidate = candidate[:32].strip()
    return candidate


def _build_prompt(text: str, settings: AppSettings) -> str:
    knowledge_hint = knowledge_service.get_knowledge_hint(_normalize(text))
    knowledge_block = knowledge_hint or "Yok"
    script_list = ", ".join(settings.allowed_scripts[:120]) or "Yok"
    script_catalog = knowledge_service.get_script_catalog_summary()
    project_context = ""
    if PROJECT_CONTEXT_PATH.exists():
        try:
            content = PROJECT_CONTEXT_PATH.read_text(encoding="utf-8").strip()
            if content:
                project_context = content[:2000]
        except OSError:
            project_context = ""

    return f"""
Sen Windows uzaktan teknik destek ajani icin komut parser'sin.
Gorevin, kullanici niyetini en uygun SISTEM AKSIYONUNA donusturmektir.
Kullanicinin dogal dil komutunu tek bir JSON nesnesine donustur.

Kurallar:
- Sadece su action degerlerinden birini kullan: {", ".join(ALLOWED_ACTIONS)}
- Sadece su location degerlerini kullan: {", ".join(ALLOWED_LOCATIONS)}
- Elinde sadece bu aksiyonlar var. Bunlar disinda bir tool, function, API, MCP server veya capability VARMIS gibi davranma.
- MCP, plugin, remote tool, harici ajan veya baska bir orkestrator dogrudan mevcut DEGIL. Kullanici bunlari istese bile yalnizca mevcut actionlardan biriyle ifade edebiliyorsan ifade et; edemiyorsan unknown don.
- Script secimi icin kural: Eger istek {script_list} listesindeki bir script tarafindan TAM ve DOGRUDAN karsilanmiyorsa run_script kullanma.
- forbidden_actions listesi: {", ".join(settings.forbidden_actions)}
- Dis bilgi / web aramasi / internet kaynakli dogrulama gerektiren isteklerde unknown don. Bu sistemde web aramasi yok.
- Karmasik veya dinamik islerde, OS komutlarinda, ekleme/silme/kontrol gibi mantiksal durumlarda action="unknown" don. Boylece planner asamasi tool-first cozum uretebilir.
- Excel/Word/Outlook gibi Office uygulamalarinda icerik yazma, hucre doldurma, calisma kitabi duzenleme, kaydetme gibi cok adimli belge/uygulama ici islemlerde type_ui yerine action="unknown" don.
- Gmail/Takvim/siteye git/PDF dokumani ac/PDF deki linke tikla gibi browser veya belge goruntuleyici odakli istekler agent_browser workflow'una aittir.
- Browser veya PDF icindeki hedefleri mevcut action setiyle guvenle ifade edemiyorsan unknown don; click_ui ancak son care fallback olsun.
- Yerel bir PDF veya dokumani varsayilan uygulamada acma istegi netse open_file kullanabilirsin.
- Kullanici birden fazla hazir script gerektiren bir is istiyorsa run_script don ve params icine script_names dizisi koy.
- Dosya islemi ve mail gibi parametreli islerde search_file, open_file, copy_file, create_folder, send_file, send_latest kullan.
- "Ac", "baslat", "olustur", "gonder", "tara", "ara", "kopyala" gibi acik fiiller varsa bunlari soyutlama; en yakin actiona indir.
- Belirsizlik varsa ama guclu bir yerel pattern varsa (ornegin "masaustune yeni klasor olustur") ilgili actioni sec.
- Gercekten belirsiz veya mevcut action seti ile ifade edilemeyen durumlarda unknown don.
- confidence 0 ile 1 arasinda olsun.
- confidence rehberi:
  - 0.90-1.00: komut acik ve action dogrudan belli
  - 0.70-0.89: action belli ama bazi parametreler cikarimla dolduruldu
  - 0.40-0.69: niyet var ama cok anlamli belirsizlik var
  - 0.00-0.39: net action secilemiyor; genelde unknown
- Aciklama, markdown veya kod blogu yazma. Sadece JSON don.

Action anlami:
- search_file: dosya bulma
- open_file: dosyayi bulup varsayilan uygulamada acma
  - copy_file: dosyayi bulup izinli klasore kopyalama
  - move_file: dosyayi bulup izinli klasore tasima
  - rename_file: dosyayi bulup yeniden adlandirma
  - delete_file: dosyayi bulup silme
- create_folder: izinli klasorde yeni klasor olusturma
- send_file: belirli bir dosyayi bulup gonderme niyeti
- send_latest: en son / en yeni dosyayi gonderme niyeti
- open_agent_browser: agent tarayici oturumu acma
- navigate_agent_browser: agent tarayici icinde URL/acik siteye gitme
- open_document_in_agent_browser: PDF/dokumani agent tarayicida acma
- click_pdf_link: PDF icindeki baglantiya gitme
- list_pdf_links: PDF icindeki baglantilari listeleme
- reuse_agent_browser_session: mevcut tarayici oturumunu kullanma
- read_agent_browser_state: tarayici durumunu ozetleme
- close_agent_browser_session: tarayici oturumunu kapatma
- open_application: uygulama veya hedef acma niyeti
- list_windows: gorunen pencereleri listeleme
- focus_window: belirli pencereye odaklanma
- wait_for_window: pencerenin acilmasini bekleme
- click_ui: bir UI hedefini tiklama
- type_ui: bir UI alanina tiklayip odaklayarak yazi/tus gonderme
- verify_ui_state: ekranin son durumunu (degisikligi) dogrulama
- read_screen: ekran durumunu toplama
- take_screenshot: ekran goruntusu alma
- create_ticket: destek bileti olusturma
- run_script: hazir PowerShell (ps1) scriptlerini calistirma
- system_status: sistem durumu isteme
- list_scripts: kullanilabilir scriptleri listeleme
- unknown: guvenli ayrisamayan veya yasakli istek

Parametre kurallari:
- search_file, open_file ve send_file icin params icinde mumkunse query, location, extension alanlarini kullan.
  - copy_file ve move_file icin params icinde query, location, extension, destination_location alanlarini kullan.
  - rename_file icin params icinde query, location, extension ve new_name kullan.
  - delete_file icin params icinde query, location ve opsiyonel extension kullan.
- create_folder icin params icinde folder_name ve destination_location alanlarini kullan.
- send_latest icin params icinde location, extension, query alanlarini kullan; query yoksa bos string ver.
- open_agent_browser icin params icinde target_url veya session_id kullan.
- navigate_agent_browser icin params icinde url veya target (gmail, calendar gibi) kullan.
- open_document_in_agent_browser icin params icinde query, location, extension kullan.
- click_pdf_link icin params icinde match (link/anahtar kelime) kullan.
- reuse_agent_browser_session icin params bos olabilir.
- read_agent_browser_state icin params bos olabilir.
- close_agent_browser_session icin params bos olabilir.
- open_application icin params icinde app_name ve opsiyonel target kullan.
- focus_window icin params icinde title_contains ve/veya process_name kullan.
- wait_for_window icin params icinde title_contains ve/veya process_name ve opsiyonel timeout_seconds kullan.
- click_ui icin params icinde text ve opsiyonel process_name/title_contains veya x/y kullan.
  - text alanina kullanicinin tum cumlesini kopyalama; sadece buton/ogede gorunmesi muhtemel kisa hedef metni ver.
- type_ui icin params icinde text_to_type (yazilacak metin) ve opsiyonel text_filter (hedef alanin ekrandaki adi) kullan.
- verify_ui_state icin params icinde opsiyonel expected_text kullan.
- create_ticket icin params icinde title ve opsiyonel description kullan.
- run_script icin params icinde script_name veya script_names kullan. (BAT/CMD kullanma, sadece PS1)
- system_status ve list_scripts ve list_windows ve read_screen ve take_screenshot icin params bos olabilir.
- extension alaninda nokta kullanma. Ornek: xlsx
- location veya destination_location belirtilmediyse desktop kullan.
- Eger komut dosya arama ile mail gonderimi birlikte iceriyorsa send_file tercih et.
- Eger "en son", "en yeni" ve mail gonderimi birlikte geciyorsa send_latest tercih et.
- Eger komut tam olarak hazir script adlarindan birine, alias'ina veya ayni amaca cok yakin bir varyantina uyuyorsa run_script kullan.

Mevcut script katalogu:
{script_catalog}

Bilgi tabani ipucu:
{knowledge_block}

Proje baglami (.teknikajan.md):
{project_context or "Yok"}

Ornekler:
- "masaustumdeki pdf dosyalarini bul" -> {{"action":"search_file","params":{{"query":"","location":"desktop","extension":"pdf"}},"confidence":0.88}}
 - "masaustundeki Enerjisa Citrix Kullanim Dokumani dosyasini bul ve ac" -> {{"action":"open_file","params":{{"query":"enerjisa citrix kullanim dokumani","location":"desktop"}},"confidence":0.9}}
 - "masaustune yeni klasor olustur" -> {{"action":"create_folder","params":{{"folder_name":"Yeni Klasor","destination_location":"desktop"}},"confidence":0.95}}
 - "masaustundeki raporu downloads klasorune tasi" -> {{"action":"move_file","params":{{"query":"rapor","location":"desktop","destination_location":"downloads"}},"confidence":0.9}}
 - "masaustundeki indirim maili dosyasini yeniden adlandir" -> {{"action":"rename_file","params":{{"query":"indirim maili","location":"desktop","new_name":"indirim-maili"}},"confidence":0.78}}
 - "masaustundeki test dosyasini sil" -> {{"action":"delete_file","params":{{"query":"test","location":"desktop"}},"confidence":0.82}}
- "en son excel dosyasini ali@example.com adresine gonder" -> {{"action":"send_latest","params":{{"query":"","location":"desktop","extension":"xlsx","recipient":"ali@example.com"}},"confidence":0.9}}
- "outlooku ac" -> {{"action":"open_application","params":{{"app_name":"outlook"}},"confidence":0.94}}
- "gorunen pencereleri listele" -> {{"action":"list_windows","params":{{}},"confidence":0.95}}
- "outlook penceresine gec" -> {{"action":"focus_window","params":{{"process_name":"outlook"}},"confidence":0.9}}
- "chrome penceresini bekle" -> {{"action":"wait_for_window","params":{{"process_name":"chrome","timeout_seconds":20}},"confidence":0.88}}
- "Outlook'ta Gonder butonuna tikla" -> {{"action":"click_ui","params":{{"text":"Gonder","process_name":"outlook"}},"confidence":0.86}}
- "gmail'e git" -> {{"action":"navigate_agent_browser","params":{{"target":"gmail"}},"confidence":0.86}}
- "Takvimde yarin toplanti olustur" -> {{"action":"navigate_agent_browser","params":{{"target":"calendar"}},"confidence":0.68}}
- "PDF deki linke tikla" -> {{"action":"click_pdf_link","params":{{"match":"link"}},"confidence":0.82}}
- "ekrani oku" -> {{"action":"read_screen","params":{{}},"confidence":0.9}}
- "ticket ac outlook mail gondermiyor" -> {{"action":"create_ticket","params":{{"title":"outlook mail gondermiyor","description":"ticket ac outlook mail gondermiyor"}},"confidence":0.92}}
- "outlooku ac ve deneme yaz" -> {{"action":"unknown","params":{{}},"confidence":0.45}}
- "mcp serverina baglan" -> {{"action":"unknown","params":{{}},"confidence":0.2}}

Kullanici komutu:
{text}
""".strip()


def _extract_location(text: str) -> str:
    normalized = _normalize(text)
    if any(token in normalized for token in ("masaustumde", "masaustunde", "masaustundeki")):
        return "desktop"
    if any(token in normalized for token in ("documentsdaki", "documentsdan", "belgelerde", "belgelerdeki", "belgelerden")):
        return "documents"
    if any(token in normalized for token in ("downloadsdaki", "downloadsdan", "indirilenlerde", "indirilenlerdeki", "indirilenlerden")):
        return "downloads"
    return "desktop"


def _extract_destination_location(text: str) -> str:
    normalized = _normalize(text)
    if any(phrase in normalized for phrase in ("belgelere", "documents klasorune", "dokumanlara")):
        return "documents"
    if any(phrase in normalized for phrase in ("indirilenlere", "downloads klasorune")):
        return "downloads"
    if any(phrase in normalized for phrase in ("masaustune", "masaustune", "masaustu")):
        return "desktop"
    return _extract_location(text)


def _extract_query(text: str) -> str:
    normalized = _normalize(text)
    normalized = re.sub(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", " ", normalized)
    cleanup_patterns = (
        r"\bbul\b",
        r"\bara\b",
        r"\bgonder\b",
        r"\bmail at\b",
        r"\byolla\b",
        r"\bkopyasini olustur\b",
        r"\bkopyasini\b",
        r"\bkopyala\b",
        r"\bicine kopyala\b",
        r"\bolustur\b",
        r"\bziple\b",
        r"\bzip\b",
        r"\barsivle\b",
        r"\barsiv\b",
        r"\btasi\b",
        r"\btasin\b",
        r"\byer degistir\b",
        r"\bdosyasini\b",
        r"\bdosyasinin\b",
        r"\bdosyayi\b",
        r"\bdosyalarini\b",
        r"\bdosyalari\b",
        r"\bklasorunu\b",
        r"\bklasoru\b",
        r"\bklasore\b",
        r"\bklasorde\b",
        r"\bisminde\b",
        r"\bo\b",
        r"\bicine\b",
        r"\badresine\b",
        r"\bemail\b",
        r"\be posta\b",
        r"\beposta\b",
        r"\bmasaustundeki\b",
        r"\bmasaustumdeki\b",
        r"\bmasaustunde\b",
        r"\bmasaustune\b",
        r"\bbelgelerdeki\b",
        r"\bdocumentsdaki\b",
        r"\bdocumentsdan\b",
        r"\bindirilenlerdeki\b",
        r"\bdownloadsdaki\b",
        r"\bdownloadsdan\b",
        r"\bdownloads klasorune\b",
        r"\bdocuments klasorune\b",
        r"\bexcelini\b",
        r"\bexcelleri\b",
        r"\bexcel\b",
        r"\bpdf\b",
        r"\bword\b",
        r"\bcsv\b",
        r"\ben son\b",
        r"\ben yeni\b",
        r"\btum\b",
        r"\bbutun\b",
        r"\bhepsi\b",
        r"\bgmail\b",
        r"\bexample\b",
        r"\bhotmail\b",
        r"\boutlook\b",
        r"\bcom\b",
        r"\bve ac\b",
        r"\bbul ve ac\b",
    )
    for pattern in cleanup_patterns:
        normalized = re.sub(pattern, " ", normalized)
    normalized = re.sub(r"\b[a-z0-9._%+-]+\s+@\s+[a-z0-9.-]+\s+\w+\b", " ", normalized)
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _sanitize_params(action: str, params: dict[str, Any], text: str) -> dict[str, Any]:
    sanitized = dict(params or {})

    if action in {"search_file", "open_file", "open_document_in_agent_browser", "copy_file", "move_file", "rename_file", "delete_file", "send_file", "send_latest"}:
        location = str(sanitized.get("location", "desktop")).lower()
        sanitized["location"] = location if location in ALLOWED_LOCATIONS else "desktop"
        raw_query = str(sanitized.get("query", "")).strip()
        extracted_query = _extract_query(text)
        sanitized["query"] = extracted_query if extracted_query and (not raw_query or len(extracted_query) <= len(raw_query)) else raw_query

        extension = sanitized.get("extension")
        if isinstance(extension, str):
            extension = extension.strip().lstrip(".").lower()
        if not extension:
            extension = _detect_extension(text)
        if extension:
            sanitized["extension"] = extension
        else:
            sanitized.pop("extension", None)

        if action in {"copy_file", "move_file"}:
            destination_location = str(
                sanitized.get("destination_location", _extract_destination_location(text))
            ).lower()
            sanitized["destination_location"] = (
                destination_location if destination_location in ALLOWED_LOCATIONS else "desktop"
            )

        if action == "rename_file":
            new_name = str(sanitized.get("new_name", "")).strip()
            if not new_name:
                rename_match = re.search(r"(?:adi(?:ni)?|ismini)\s+(.+?)(?:\s+yap|\s+olarak|\s+degistir|$)", text, flags=re.IGNORECASE)
                if rename_match:
                    new_name = rename_match.group(1).strip(" .")
            if new_name:
                sanitized["new_name"] = new_name

        recipient = sanitized.get("recipient")
        if isinstance(recipient, str):
            recipient = recipient.strip()
        if not recipient:
            recipient = _extract_email(text)
        if recipient and action in {"send_file", "send_latest"}:
            sanitized["recipient"] = recipient
        else:
            sanitized.pop("recipient", None)

    elif action == "create_folder":
        folder_name = str(sanitized.get("folder_name", "")).strip()
        if not folder_name:
            folder_name = "Yeni Klasor"
        destination_location = str(
            sanitized.get("destination_location", _extract_destination_location(text))
        ).lower()
        sanitized = {
            "folder_name": folder_name,
            "destination_location": destination_location if destination_location in ALLOWED_LOCATIONS else "desktop",
        }
    elif action == "open_agent_browser":
        target_url = str(sanitized.get("target_url", "")).strip()
        sanitized = {"target_url": target_url} if target_url else {}
    elif action == "navigate_agent_browser":
        url = str(sanitized.get("url", "")).strip()
        target = str(sanitized.get("target", "")).strip()
        sanitized = {**({"url": url} if url else {}), **({"target": target} if target else {})}
    elif action == "click_pdf_link":
        match = str(sanitized.get("match", "")).strip() or _simplify_click_target("", text)
        sanitized = {"match": match} if match else {}
    elif action in {"list_pdf_links", "reuse_agent_browser_session", "read_agent_browser_state", "close_agent_browser_session"}:
        sanitized = {}
    elif action == "open_application":
        app_name = str(sanitized.get("app_name", "")).strip()
        target = str(sanitized.get("target", "")).strip()
        sanitized = {"app_name": app_name, **({"target": target} if target else {})} if app_name else {}
    elif action == "focus_window":
        title_contains = str(sanitized.get("title_contains", "")).strip()
        process_name = str(sanitized.get("process_name", "")).strip()
        sanitized = {
            **({"title_contains": title_contains} if title_contains else {}),
            **({"process_name": process_name} if process_name else {}),
        }
    elif action == "wait_for_window":
        title_contains = str(sanitized.get("title_contains", "")).strip()
        process_name = str(sanitized.get("process_name", "")).strip()
        timeout_seconds = int(sanitized.get("timeout_seconds", 20) or 20)
        sanitized = {
            **({"title_contains": title_contains} if title_contains else {}),
            **({"process_name": process_name} if process_name else {}),
            "timeout_seconds": max(1, min(timeout_seconds, 120)),
        }
    elif action == "click_ui":
        text_value = _simplify_click_target(str(sanitized.get("text", "")).strip(), text)
        title_contains = str(sanitized.get("title_contains", "")).strip()
        process_name = str(sanitized.get("process_name", "")).strip()
        raw_x = sanitized.get("x")
        raw_y = sanitized.get("y")
        button = str(sanitized.get("button", "left")).strip().lower() or "left"
        normalized: dict[str, Any] = {**({"text": text_value} if text_value else {}), **({"title_contains": title_contains} if title_contains else {}), **({"process_name": process_name} if process_name else {}), "button": button}
        if raw_x is not None and raw_y is not None:
            normalized["x"] = int(raw_x)
            normalized["y"] = int(raw_y)
        sanitized = normalized
    elif action == "type_ui":
        text_to_type = str(sanitized.get("text_to_type", "")).strip()
        text_filter = str(sanitized.get("text_filter", "")).strip()
        title_contains = str(sanitized.get("title_contains", "")).strip()
        process_name = str(sanitized.get("process_name", "")).strip()
        sanitized = {"text_to_type": text_to_type}
        if text_filter: sanitized["text_filter"] = text_filter
        if title_contains: sanitized["title_contains"] = title_contains
        if process_name: sanitized["process_name"] = process_name
    elif action == "verify_ui_state":
        expected_text = str(sanitized.get("expected_text", "")).strip()
        sanitized = {"expected_text": expected_text} if expected_text else {}
    elif action in {"list_windows", "read_screen", "take_screenshot"}:
        sanitized = {}
    elif action == "create_ticket":
        title = str(sanitized.get("title", "")).strip() or _extract_ticket_summary(text)
        description = str(sanitized.get("description", "")).strip() or text.strip()
        sanitized = {"title": title[:120], "description": description}
    elif action == "run_script":
        script_names = sanitized.get("script_names")
        if isinstance(script_names, list):
            cleaned_names = [str(item).strip() for item in script_names if str(item).strip()]
            if len(cleaned_names) > 1:
                sanitized = {"script_names": cleaned_names}
            elif cleaned_names:
                sanitized = {"script_name": cleaned_names[0]}
            else:
                script_name = sanitized.get("script_name")
                sanitized = {"script_name": str(script_name).strip() if script_name is not None else ""}
        else:
            script_name = sanitized.get("script_name")
            sanitized = {"script_name": str(script_name).strip() if script_name is not None else ""}
    else:
        sanitized = {}

    return sanitized


def _fallback_parse(text: str) -> ParsedCommand:
    normalized = _normalize(text)
    knowledge_hint = knowledge_service.get_knowledge_hint(normalized)
    workflow_profile = route_to_workflow_profile(text)
    agent_browser_intent = _classify_agent_browser_intent(text)

    if _looks_like_multi_step_file_workflow(text):
        return ParsedCommand(action="unknown", confidence=0.9, knowledge_hint=knowledge_hint, workflow_profile=workflow_profile)

    if _looks_like_excel_edit_workflow(text):
        return ParsedCommand(action="unknown", confidence=0.9, knowledge_hint=knowledge_hint, workflow_profile=workflow_profile)

    if any(phrase in normalized for phrase in ("sistem durumu", "durum goster", "durumu goster", "cpu", "ram", "disk")):
        return ParsedCommand(action="system_status", confidence=0.9, knowledge_hint=knowledge_hint, workflow_profile=workflow_profile)

    if "dosyasina" in normalized and any(token in normalized for token in (" yaz", "ekle", "icerigini yaz", "metin ekle")):
        return ParsedCommand(action="unknown", confidence=0.9, knowledge_hint=knowledge_hint, workflow_profile=workflow_profile)

    if "klasor" in normalized and any(token in normalized for token in ("txt", "metin dosyasi", "txt dosyasi", "dosyasi ekle")):
        return ParsedCommand(action="unknown", confidence=0.82, knowledge_hint=knowledge_hint, workflow_profile=workflow_profile)

    if _looks_like_folder_archive_workflow(text):
        return ParsedCommand(action="unknown", confidence=0.9, knowledge_hint=knowledge_hint, workflow_profile=workflow_profile)

    if any(phrase in normalized for phrase in ("scriptleri listele", "script listesi", "hangi script", "scriptler")):
        return ParsedCommand(action="list_scripts", confidence=0.88, knowledge_hint=knowledge_hint)

    if any(phrase in normalized for phrase in ("pencereleri listele", "gorunen pencereleri listele", "acik pencereler", "window list")):
        return ParsedCommand(action="list_windows", confidence=0.94, knowledge_hint=knowledge_hint)

    if any(phrase in normalized for phrase in (" penceresine gec", " penceresini odakla", " pencereye gec", " odaklan")):
        app_aliases = {
            "outlook": "outlook",
            "chrome": "chrome",
            "google chrome": "chrome",
            "excel": "excel",
            "word": "word",
            "notepad": "notepad",
            "not defteri": "notepad",
            "paint": "paint",
            "explorer": "explorer",
        }
        for alias, app_name in app_aliases.items():
            if alias in normalized:
                return ParsedCommand(
                    action="focus_window",
                    params={"process_name": app_name},
                    confidence=0.9,
                    knowledge_hint=knowledge_hint,
                )

    if agent_browser_intent == "open_document_in_agent_browser":
        extension = _detect_extension(text) or ("pdf" if "pdf" in normalized else None)
        return ParsedCommand(
            action="open_document_in_agent_browser",
            params={
                "query": _extract_query(text),
                "location": _extract_location(text),
                **({"extension": extension} if extension else {}),
            },
            confidence=0.89,
            knowledge_hint=knowledge_hint,
            workflow_profile=workflow_profile,
        )

    if agent_browser_intent == "navigate_agent_browser":
        target = None
        normalized_text = _normalize(text)
        if "gmail" in normalized_text:
            target = "gmail"
        elif any(token in normalized_text for token in ("takvim", "calendar", "calender", "calendari", "calendarda")):
            target = "calendar"
        return ParsedCommand(
            action="navigate_agent_browser",
            params={
                **({"url": _extract_url(text)} if _extract_url(text) else {}),
                **({"target": target} if target else {}),
            },
            confidence=0.86,
            knowledge_hint=knowledge_hint,
            workflow_profile=workflow_profile,
        )

    if agent_browser_intent == "click_pdf_link":
        return ParsedCommand(
            action="click_pdf_link",
            params={"match": _simplify_click_target(_extract_query(text), text)},
            confidence=0.86,
            knowledge_hint=knowledge_hint,
            workflow_profile=workflow_profile,
        )

    if agent_browser_intent == "reuse_agent_browser_session":
        return ParsedCommand(
            action="reuse_agent_browser_session",
            confidence=0.84,
            knowledge_hint=knowledge_hint,
            workflow_profile=workflow_profile,
        )

    if any(phrase in normalized for phrase in (" penceresini bekle", " acilmasini bekle", " ekranini bekle")):
        app_aliases = {
            "outlook": "outlook",
            "chrome": "chrome",
            "google chrome": "chrome",
            "excel": "excel",
            "word": "word",
            "notepad": "notepad",
            "not defteri": "notepad",
            "paint": "paint",
            "explorer": "explorer",
        }
        for alias, app_name in app_aliases.items():
            if alias in normalized:
                return ParsedCommand(
                    action="wait_for_window",
                    params={"process_name": app_name, "timeout_seconds": 20},
                    confidence=0.88,
                    knowledge_hint=knowledge_hint,
                )

    if any(phrase in normalized for phrase in (" tikla", " tıkla", " butonuna bas", " butonuna tikla", " dugmesine tikla", " dugmesine bas")):
        app_aliases = {
            "outlook": "outlook",
            "chrome": "chrome",
            "google chrome": "chrome",
            "excel": "excel",
            "word": "word",
            "notepad": "notepad",
            "not defteri": "notepad",
            "paint": "paint",
            "explorer": "explorer",
        }
        text_match = re.search(r"([A-Za-z0-9ÇĞİÖŞÜçğıöşü_ -]+?)\s+(?:butonuna bas|butonuna tikla|dugmesine tikla|dugmesine bas|tikla|tıkla)", text, flags=re.IGNORECASE)
        clicked_text = ""
        if text_match:
            clicked_text = text_match.group(1).strip()
        clicked_text = re.sub(r"\b(outlook|chrome|google chrome|excel|word|notepad|not defteri|paint|explorer)(?:'?[td][ae])?\b", "", clicked_text, flags=re.IGNORECASE)
        clicked_text = re.sub(r"\b(?:ta|te|da|de|nda|nde)\b", "", clicked_text, flags=re.IGNORECASE)
        clicked_text = re.sub(r"\s+", " ", clicked_text).strip(" -:")
        clicked_text = _simplify_click_target(clicked_text, text)
        params: dict[str, Any] = {"button": "left"}
        if clicked_text:
            params["text"] = clicked_text
        for alias, app_name in app_aliases.items():
            if alias in normalized:
                params["process_name"] = app_name
                break
        if params.get("text"):
            return ParsedCommand(
                action="click_ui",
                params=params,
                confidence=0.86,
                knowledge_hint=knowledge_hint,
            )

    if agent_browser_intent in {"navigate_agent_browser", "open_agent_browser", "reuse_agent_browser_session"}:
        return ParsedCommand(
            action=agent_browser_intent,
            params={},
            confidence=0.86,
            knowledge_hint=knowledge_hint,
            workflow_profile=workflow_profile,
        )

    if any(
        phrase in normalized
        for phrase in (
            "ticket ac",
            "ticket olustur",
            "destek bileti",
            "destek kaydi",
            "bilet ac",
            "kayit ac",
        )
    ):
        return ParsedCommand(
            action="create_ticket",
            params={
                "title": _extract_ticket_summary(text),
                "description": text.strip(),
            },
            confidence=0.92,
            knowledge_hint=knowledge_hint,
        )

    if any(phrase in normalized for phrase in (" yaz", "gir ", "tusla")):
        type_match = re.search(r"['\"]?(.+?)['\"]?\s*(?:diye|olarak)?\s*yaz", text, flags=re.IGNORECASE)
        if type_match:
            return ParsedCommand(
                action="type_ui",
                params={"text_to_type": type_match.group(1).strip()},
                confidence=0.8,
                knowledge_hint=knowledge_hint,
            )

    if any(phrase in normalized for phrase in ("dogrula", "oldu mu", "kontrol et")):
        return ParsedCommand(action="verify_ui_state", confidence=0.85, knowledge_hint=knowledge_hint)

    if any(phrase in normalized for phrase in ("ekrani oku", "ekrani analiz et", "screeni oku", "screeni analiz et")):
        return ParsedCommand(action="read_screen", confidence=0.9, knowledge_hint=knowledge_hint)

    if any(phrase in normalized for phrase in ("ekran goruntusu al", "ekran resmi al", "screenshot al", "ss al")):
        return ParsedCommand(action="take_screenshot", confidence=0.92, knowledge_hint=knowledge_hint)

    matched_scripts = _match_script_aliases(text)
    if len(matched_scripts) > 1:
        return ParsedCommand(
            action="run_script",
            params={"script_names": matched_scripts},
            confidence=0.92,
            knowledge_hint=knowledge_hint,
        )
    if matched_scripts:
        return ParsedCommand(
            action="run_script",
            params={"script_name": matched_scripts[0]},
            confidence=0.9,
            knowledge_hint=knowledge_hint,
        )

    if any(marker in normalized for marker in MULTI_STEP_MARKERS):
        if any(word in normalized for word in ("ekran resmi", "screenshot", "mail", "gonder", "kopya", "kopyala")):
            return ParsedCommand(action="unknown", confidence=0.55, knowledge_hint=knowledge_hint)
        if " ac" in normalized and not any(
            phrase in normalized
            for phrase in ("bul ve ac", "bulup ac", "ac ve goster", "dosyayi ac", "dokumani ac", "dokumani bul ve ac", "dosyayi bul ve ac")
        ):
            return ParsedCommand(action="unknown", confidence=0.55, knowledge_hint=knowledge_hint)

    extension = _detect_extension(text)
    location = _extract_location(text)
    destination_location = _extract_destination_location(text)
    query = _extract_query(text)
    recipient = _extract_email(text)

    if any(phrase in normalized for phrase in ("en son", "en yeni")) and any(
        phrase in normalized for phrase in ("gonder", "mail", "yolla")
    ):
        return ParsedCommand(
            action="send_latest",
            params={
                "query": query,
                "location": location,
                **({"extension": extension} if extension else {}),
                **({"recipient": recipient} if recipient else {}),
            },
            confidence=0.78,
            knowledge_hint=knowledge_hint,
        )

    if any(phrase in normalized for phrase in ("bul ve ac", "bulup ac", "ac ve goster", "dosyayi ac", "dokumani ac", "dokumani bul ve ac", "dosyayi bul ve ac")):
        return ParsedCommand(
            action="open_file",
            params={
                "query": query,
                "location": location,
                **({"extension": extension} if extension else {}),
            },
            confidence=0.86,
            knowledge_hint=knowledge_hint,
        )

    if any(phrase in normalized for phrase in ("kopya", "kopyasini olustur", "kopyala")):
        return ParsedCommand(
            action="copy_file",
            params={
                "query": query,
                "location": location,
                "destination_location": destination_location,
                **({"extension": extension} if extension else {}),
            },
            confidence=0.84,
            knowledge_hint=knowledge_hint,
        )

    if any(phrase in normalized for phrase in (" tasi", " tasi ", "tasin", "move et", "yer degistir")):
        return ParsedCommand(
            action="move_file",
            params={
                "query": query,
                "location": location,
                "destination_location": destination_location,
                **({"extension": extension} if extension else {}),
            },
            confidence=0.84,
            knowledge_hint=knowledge_hint,
        )

    if any(phrase in normalized for phrase in ("yeniden adlandir", "adini degistir", "ismini degistir", "rename", " adini ", " ismini ")):
        rename_match = re.search(r"(?:adi(?:ni)?|ismini)\s+(.+?)(?:\s+yap|\s+olarak|\s+degistir|$)", text, flags=re.IGNORECASE)
        new_name = rename_match.group(1).strip(" .") if rename_match else ""
        if new_name:
            return ParsedCommand(
                action="rename_file",
                params={
                    "query": query,
                    "location": location,
                    **({"extension": extension} if extension else {}),
                    "new_name": new_name,
                },
                confidence=0.8,
                knowledge_hint=knowledge_hint,
            )

    if any(phrase in normalized for phrase in (" sil", "sil ", "kaldir", "delete")):
        return ParsedCommand(
            action="delete_file",
            params={
                "query": query,
                "location": location,
                **({"extension": extension} if extension else {}),
            },
            confidence=0.8,
            knowledge_hint=knowledge_hint,
        )

    if any(phrase in normalized for phrase in ("klasor olustur", "klasor ac", "yeni klasor", "folder olustur", "folder create")):
        query = _extract_query(text)
        folder_name = query or "Yeni Klasor"
        return ParsedCommand(
            action="create_folder",
            params={
                "folder_name": folder_name,
                "destination_location": destination_location,
            },
            confidence=0.9,
            knowledge_hint=knowledge_hint,
        )

    if any(phrase in normalized for phrase in ("gonder", "mail at", "yolla")):
        return ParsedCommand(
            action="send_file",
            params={
                "query": query,
                "location": location,
                **({"extension": extension} if extension else {}),
                **({"recipient": recipient} if recipient else {}),
            },
            confidence=0.74,
            knowledge_hint=knowledge_hint,
        )

    app_aliases = {
        "outlook": "outlook",
        "chrome": "chrome",
        "google chrome": "chrome",
        "excel": "excel",
        "word": "word",
        "notepad": "notepad",
        "not defteri": "notepad",
        "hesap makinesi": "calculator",
        "calculator": "calculator",
        "paint": "paint",
        "explorer": "explorer",
        "dosya gezgini": "explorer",
    }
    if any(phrase in normalized for phrase in (" ac", " baslat", " calistir")):
        for alias, app_name in app_aliases.items():
            if alias in normalized:
                return ParsedCommand(
                    action="open_application",
                    params={"app_name": app_name},
                    confidence=0.9,
                    knowledge_hint=knowledge_hint,
                )

    if any(phrase in normalized for phrase in ("bul", "ara", "dosya", "excel", "pdf", "word", "csv")):
        return ParsedCommand(
            action="search_file",
            params={"query": query, "location": location, **({"extension": extension} if extension else {})},
            confidence=0.72,
            knowledge_hint=knowledge_hint,
        )

    return ParsedCommand(action="unknown", confidence=0.2, knowledge_hint=knowledge_hint)


def parse_command(text: str, settings: AppSettings | None = None) -> ParsedCommand:
    text = _normalize_command_text(text)
    workflow_profile = route_to_workflow_profile(text)
    if _looks_like_multi_step_file_workflow(text):
        return ParsedCommand(
            action="unknown",
            confidence=0.9,
            knowledge_hint=knowledge_service.get_knowledge_hint(_normalize(text)),
            workflow_profile=workflow_profile,
        )
    if _looks_like_excel_edit_workflow(text):
        return ParsedCommand(
            action="unknown",
            confidence=0.9,
            knowledge_hint=knowledge_service.get_knowledge_hint(_normalize(text)),
            workflow_profile=workflow_profile,
        )
    active_settings = settings or load_settings()
    fallback_candidate = _fallback_parse(text)
    agent_browser_intent = _classify_agent_browser_intent(text)
    if active_settings.ai_provider == "openrouter" and not active_settings.openrouter_api_key:
        return fallback_candidate
    if active_settings.ai_provider == "gemini" and not active_settings.gemini_api_key:
        return fallback_candidate

    try:
        if active_settings.ai_provider == "openrouter":
            payload = parse_command_with_openrouter(
                api_key=active_settings.openrouter_api_key,
                model=active_settings.openrouter_model,
                prompt=_build_prompt(text, active_settings),
            )
        else:
            payload = parse_command_with_gemini(
                api_key=active_settings.gemini_api_key,
                model=active_settings.gemini_model,
                prompt=_build_prompt(text, active_settings),
            )
    except Exception:
        return fallback_candidate

    action = payload.action if payload.action in ALLOWED_ACTIONS else "unknown"
    params = _sanitize_params(action, payload.params, text)
    normalized_text = _normalize(text)
    if agent_browser_intent == "click_pdf_link" and action in {"click_ui", "unknown", "search_file"}:
        action = "click_pdf_link"
        params = _sanitize_params(action, fallback_candidate.params or {}, text)
    elif agent_browser_intent in {"navigate_agent_browser", "open_agent_browser", "reuse_agent_browser_session"} and action in {
        "search_file",
        "open_file",
        "unknown",
    }:
        action = agent_browser_intent
        params = _sanitize_params(action, fallback_candidate.params or {}, text)
    elif (
        action == "search_file"
        and (agent_browser_intent == "open_document_in_agent_browser" or ("pdf" in normalized_text and " ac" in normalized_text))
    ):
        action = "open_document_in_agent_browser"
        params = _sanitize_params(action, fallback_candidate.params or {}, text)
    if action == "unknown" or (action == "run_script" and not (params.get("script_name") or params.get("script_names"))):
        return fallback_candidate
    if float(payload.confidence) < 0.6:
        return fallback_candidate

    return ParsedCommand(
        action=action,
        params=params,
        confidence=max(0.0, min(float(payload.confidence), 1.0)),
        knowledge_hint=knowledge_service.get_knowledge_hint(_normalize(text)),
        workflow_profile=workflow_profile,
    )
