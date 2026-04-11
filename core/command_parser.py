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
from core.config import AppSettings, load_settings
from core.knowledge import KnowledgeService

knowledge_service = KnowledgeService()

BASE_DIR = Path(__file__).resolve().parent.parent

ALLOWED_ACTIONS = (
    "search_file",
    "copy_file",
    "move_file",
    "rename_file",
    "delete_file",
    "create_folder",
    "send_file",
    "send_latest",
    "open_application",
    "list_windows",
    "focus_window",
    "wait_for_window",
    "click_ui",
    "read_screen",
    "take_screenshot",
    "run_script",
    "system_status",
    "list_scripts",
    "unknown",
)

ALLOWED_LOCATIONS = ("desktop", "documents", "downloads")
MULTI_STEP_MARKERS = (" ve ", " sonra ", " ardindan ", " ardından ")


@dataclass(slots=True)
class ParsedCommand:
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    knowledge_hint: str | None = None


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
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


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


def _build_prompt(text: str, settings: AppSettings) -> str:
    knowledge_hint = knowledge_service.get_knowledge_hint(_normalize(text))
    knowledge_block = knowledge_hint or "Yok"
    script_list = ", ".join(settings.allowed_scripts[:120]) or "Yok"
    script_catalog = knowledge_service.get_script_catalog_summary()

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
- Karmasik veya dinamik islerde, OS komutlarinda, ekleme/silme/kontrol gibi mantiksal durumlarda action="unknown" don. Boylece planner asamasi tool-first cozum uretebilir.
- Kullanici birden fazla hazir script gerektiren bir is istiyorsa run_script don ve params icine script_names dizisi koy.
- Dosya islemi ve mail gibi parametreli islerde search_file, copy_file, create_folder, send_file, send_latest kullan.
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
  - copy_file: dosyayi bulup izinli klasore kopyalama
  - move_file: dosyayi bulup izinli klasore tasima
  - rename_file: dosyayi bulup yeniden adlandirma
  - delete_file: dosyayi bulup silme
- create_folder: izinli klasorde yeni klasor olusturma
- send_file: belirli bir dosyayi bulup gonderme niyeti
- send_latest: en son / en yeni dosyayi gonderme niyeti
- open_application: uygulama veya hedef acma niyeti
- list_windows: gorunen pencereleri listeleme
- focus_window: belirli pencereye odaklanma
- wait_for_window: pencerenin acilmasini bekleme
- click_ui: bir UI hedefini tiklama
- read_screen: ekran durumunu toplama
- take_screenshot: ekran goruntusu alma
- run_script: hazir bat/ps scriptlerini calistirma
- system_status: sistem durumu isteme
- list_scripts: kullanilabilir scriptleri listeleme
- unknown: guvenli ayrisamayan veya yasakli istek

Parametre kurallari:
- search_file ve send_file icin params icinde mumkunse query, location, extension alanlarini kullan.
  - copy_file ve move_file icin params icinde query, location, extension, destination_location alanlarini kullan.
  - rename_file icin params icinde query, location, extension ve new_name kullan.
  - delete_file icin params icinde query, location ve opsiyonel extension kullan.
- create_folder icin params icinde folder_name ve destination_location alanlarini kullan.
- send_latest icin params icinde location, extension, query alanlarini kullan; query yoksa bos string ver.
- open_application icin params icinde app_name ve opsiyonel target kullan.
- focus_window icin params icinde title_contains ve/veya process_name kullan.
- wait_for_window icin params icinde title_contains ve/veya process_name ve opsiyonel timeout_seconds kullan.
- click_ui icin params icinde text ve opsiyonel process_name/title_contains veya x/y kullan.
- run_script icin params icinde script_name veya script_names kullan.
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

Ornekler:
- "masaustumdeki pdf dosyalarini bul" -> {{"action":"search_file","params":{{"query":"","location":"desktop","extension":"pdf"}},"confidence":0.88}}
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
- "ekrani oku" -> {{"action":"read_screen","params":{{}},"confidence":0.9}}
- "outlooku ac ve deneme yaz" -> {{"action":"unknown","params":{{}},"confidence":0.45}}
- "mcp serverina baglan" -> {{"action":"unknown","params":{{}},"confidence":0.2}}

Kullanici komutu:
{text}
""".strip()


def _extract_location(text: str) -> str:
    normalized = _normalize(text)
    if "documents" in normalized or "belgeler" in normalized:
        return "documents"
    if "downloads" in normalized or "indirilen" in normalized or "download" in normalized:
        return "downloads"
    return "desktop"


def _extract_destination_location(text: str) -> str:
    normalized = _normalize(text)
    if any(phrase in normalized for phrase in ("masaustune", "masaustune", "masaustu")):
        return "desktop"
    if any(phrase in normalized for phrase in ("belgelere", "documents", "dokumanlara")):
        return "documents"
    if any(phrase in normalized for phrase in ("indirilenlere", "downloads")):
        return "downloads"
    return _extract_location(text)


def _extract_query(text: str) -> str:
    normalized = _normalize(text)
    cleanup_patterns = (
        r"\bbul\b",
        r"\bara\b",
        r"\bgonder\b",
        r"\bmail at\b",
        r"\byolla\b",
        r"\bkopyasini olustur\b",
        r"\bkopyasini\b",
        r"\bkopyala\b",
        r"\bolustur\b",
        r"\bdosyasini\b",
        r"\bdosyasinin\b",
        r"\bdosyayi\b",
        r"\bmasaustundeki\b",
        r"\bmasaustune\b",
        r"\bbelgelerdeki\b",
        r"\bindirilenlerdeki\b",
        r"\bexcelini\b",
        r"\bexcel\b",
        r"\bpdf\b",
        r"\bword\b",
        r"\bcsv\b",
        r"\ben son\b",
        r"\ben yeni\b",
    )
    for pattern in cleanup_patterns:
        normalized = re.sub(pattern, " ", normalized)
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _sanitize_params(action: str, params: dict[str, Any], text: str) -> dict[str, Any]:
    sanitized = dict(params or {})

    if action in {"search_file", "copy_file", "move_file", "rename_file", "delete_file", "send_file", "send_latest"}:
        location = str(sanitized.get("location", "desktop")).lower()
        sanitized["location"] = location if location in ALLOWED_LOCATIONS else "desktop"
        sanitized["query"] = str(sanitized.get("query", "")).strip()

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
        text_value = str(sanitized.get("text", "")).strip()
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
    elif action in {"list_windows", "read_screen", "take_screenshot"}:
        sanitized = {}
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

    if any(phrase in normalized for phrase in ("sistem durumu", "durum goster", "durumu goster", "cpu", "ram", "disk")):
        return ParsedCommand(action="system_status", confidence=0.9, knowledge_hint=knowledge_hint)

    if "dosyasina" in normalized and any(token in normalized for token in (" yaz", "ekle", "icerigini yaz", "metin ekle")):
        return ParsedCommand(action="unknown", confidence=0.9, knowledge_hint=knowledge_hint)

    if "klasor" in normalized and any(token in normalized for token in ("txt", "metin dosyasi", "txt dosyasi", "dosyasi ekle")):
        return ParsedCommand(action="unknown", confidence=0.82, knowledge_hint=knowledge_hint)

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
        if any(word in normalized for word in ("ekran resmi", "screenshot", "ac", "mail", "gonder", "kopya", "kopyala")):
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
    active_settings = settings or load_settings()
    if not active_settings.gemini_api_key:
        return _fallback_parse(text)

    payload = parse_command_with_gemini(
        api_key=active_settings.gemini_api_key,
        model=active_settings.gemini_model,
        prompt=_build_prompt(text, active_settings),
    )

    action = payload.action if payload.action in ALLOWED_ACTIONS else "unknown"
    params = _sanitize_params(action, payload.params, text)
    if action == "unknown" or (action == "run_script" and not (params.get("script_name") or params.get("script_names"))):
        return _fallback_parse(text)

    return ParsedCommand(
        action=action,
        params=params,
        confidence=max(0.0, min(float(payload.confidence), 1.0)),
        knowledge_hint=knowledge_service.get_knowledge_hint(_normalize(text)),
    )
