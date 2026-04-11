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
    "send_file",
    "send_latest",
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

    return f"""
Sen Windows uzaktan teknik destek ajani icin komut parser'sin.
Kullanicinin dogal dil komutunu tek bir JSON nesnesine donustur.

Kurallar:
- Sadece su action degerlerinden birini kullan: {", ".join(ALLOWED_ACTIONS)}
- Sadece su location degerlerini kullan: {", ".join(ALLOWED_LOCATIONS)}
- Script secimi icin kurallar: Eger istegi {script_list} listesindeki bir script TAM OLARAK (%100) karsilamiyorsa (ornek: kullanici yazici ac defil de YAZICI EKLE/BUL diyorsa) KESINLIKLE 'run_script' KULLANMA.
- forbidden_actions listesi: {", ".join(settings.forbidden_actions)}
- Karmasik veya dinamik islerde, OS komutlarinda, ekleme/silme/kontrol gibi mantiksal durumlarda DAIMA action="unknown" don. Boylece sistem onu dinamik olarak isleyebilir.
- Kullanici birden fazla hazir script gerektiren bir is istiyorsa run_script don ve params icine script_names dizisi koy.
- Dosya islemi ve mail gibi parametreli islerde search_file, copy_file, send_file, send_latest kullan.
- Emin degilsen VEYA isin icinde if-else, kontrol, ekleme (orn: yazici ekle) varsa action="unknown" don.
- confidence 0 ile 1 arasinda olsun.
- Aciklama, markdown veya kod blogu yazma. Sadece JSON don.

Action anlami:
- search_file: dosya bulma
- copy_file: dosyayi bulup izinli klasore kopyalama
- send_file: belirli bir dosyayi bulup gonderme niyeti
- send_latest: en son / en yeni dosyayi gonderme niyeti
- run_script: hazir bat/ps scriptlerini calistirma
- system_status: sistem durumu isteme
- list_scripts: kullanilabilir scriptleri listeleme
- unknown: guvenli ayrisamayan veya yasakli istek

Parametre kurallari:
- search_file ve send_file icin params icinde mumkunse query, location, extension alanlarini kullan.
- copy_file icin params icinde query, location, extension, destination_location alanlarini kullan.
- send_latest icin params icinde location, extension, query alanlarini kullan; query yoksa bos string ver.
- run_script icin params icinde script_name veya script_names kullan.
- system_status ve list_scripts icin params bos olabilir.
- extension alaninda nokta kullanma. Ornek: xlsx
- location veya destination_location belirtilmediyse desktop kullan.

Bilgi tabani ipucu:
{knowledge_block}

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

    if action in {"search_file", "copy_file", "send_file", "send_latest"}:
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

        if action == "copy_file":
            destination_location = str(
                sanitized.get("destination_location", _extract_destination_location(text))
            ).lower()
            sanitized["destination_location"] = (
                destination_location if destination_location in ALLOWED_LOCATIONS else "desktop"
            )

        recipient = sanitized.get("recipient")
        if isinstance(recipient, str):
            recipient = recipient.strip()
        if not recipient:
            recipient = _extract_email(text)
        if recipient and action in {"send_file", "send_latest"}:
            sanitized["recipient"] = recipient
        else:
            sanitized.pop("recipient", None)

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

    if any(phrase in normalized for phrase in ("scriptleri listele", "script listesi", "hangi script", "scriptler")):
        return ParsedCommand(action="list_scripts", confidence=0.88, knowledge_hint=knowledge_hint)

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
