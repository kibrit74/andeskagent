from __future__ import annotations

import json
import os
import getpass
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "settings.json"
DEFAULT_WHITELIST_PATH = BASE_DIR / "config" / "whitelist.json"
DEFAULT_SQLITE_PATH = BASE_DIR / "data" / "app.db"
DEFAULT_LOG_PATH = BASE_DIR / "logs" / "ops.log"
DEFAULT_SCRIPT_MANIFEST_PATH = BASE_DIR / "scripts" / "manifest.json"


@dataclass(slots=True)
class AppSettings:
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_base_url: str = "http://127.0.0.1:8000"
    bearer_token: str = "change-me"
    sqlite_path: Path = DEFAULT_SQLITE_PATH
    log_path: Path = DEFAULT_LOG_PATH
    allowed_folders: list[str] = field(default_factory=list)
    allowed_scripts: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    mail_recipients_whitelist: list[str] = field(default_factory=list)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    default_mail_from: str = ""
    mail_transport: str = "playwright"
    playwright_browser_channel: str = "msedge"
    playwright_user_data_dir: str = "data/playwright-edge-profile"
    playwright_headless: bool = False
    playwright_mail_url: str = "https://mail.google.com/mail/u/0/#inbox"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        expanded = value.replace("{user}", getpass.getuser())
        return os.path.expanduser(os.path.expandvars(expanded))
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def _load_manifest_script_names(path: Path | None = None) -> list[str]:
    manifest_path = path or DEFAULT_SCRIPT_MANIFEST_PATH
    raw = _load_json(manifest_path)
    names: list[str] = []
    for item in raw.get("scripts", []):
        name = str(item.get("name", "")).strip()
        if name:
            names.append(name)
    return names


def load_settings(config_path: Path | None = None) -> AppSettings:
    config_path = config_path or DEFAULT_CONFIG_PATH
    raw = _expand(_load_json(config_path))
    whitelist = _expand(_load_json(DEFAULT_WHITELIST_PATH))

    sqlite_path = Path(raw.get("sqlite_path", DEFAULT_SQLITE_PATH))
    log_path = Path(raw.get("log_path", DEFAULT_LOG_PATH))

    manifest_scripts = _load_manifest_script_names()
    allowed_scripts = list(
        dict.fromkeys(
            [
                *list(whitelist.get("allowed_scripts", raw.get("allowed_scripts", []))),
                *manifest_scripts,
            ]
        )
    )

    settings = AppSettings(
        api_host=raw.get("api_host", AppSettings.api_host),
        api_port=int(raw.get("api_port", AppSettings.api_port)),
        api_base_url=raw.get("api_base_url", AppSettings.api_base_url),
        bearer_token=raw.get("bearer_token", os.environ.get("TEKNIKAJAN_BEARER_TOKEN", AppSettings.bearer_token)),
        sqlite_path=sqlite_path,
        log_path=log_path,
        allowed_folders=list(whitelist.get("allowed_folders", raw.get("allowed_folders", []))),
        allowed_scripts=allowed_scripts,
        forbidden_actions=list(whitelist.get("forbidden_actions", raw.get("forbidden_actions", []))),
        mail_recipients_whitelist=list(whitelist.get("mail_recipients_whitelist", raw.get("mail_recipients_whitelist", []))),
        smtp_host=raw.get("smtp_host", ""),
        smtp_port=int(raw.get("smtp_port", 587)),
        smtp_username=raw.get("smtp_username", ""),
        smtp_password=raw.get("smtp_password", ""),
        smtp_use_tls=bool(raw.get("smtp_use_tls", True)),
        default_mail_from=raw.get("default_mail_from", raw.get("smtp_username", "")),
        mail_transport=raw.get("mail_transport", "playwright"),
        playwright_browser_channel=raw.get("playwright_browser_channel", "msedge"),
        playwright_user_data_dir=raw.get("playwright_user_data_dir", "data/playwright-edge-profile"),
        playwright_headless=bool(raw.get("playwright_headless", False)),
        playwright_mail_url=raw.get("playwright_mail_url", "https://mail.google.com/mail/u/0/#inbox"),
        gemini_api_key=raw.get("gemini_api_key", os.environ.get("GEMINI_API_KEY", "")),
        gemini_model=raw.get("gemini_model", os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")),
    )
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    return settings


def load_whitelist(path: Path | None = None) -> dict[str, list[str]]:
    whitelist_path = path or DEFAULT_WHITELIST_PATH
    raw = _expand(_load_json(whitelist_path))
    return {
        "allowed_folders": list(raw.get("allowed_folders", [])),
        "allowed_scripts": list(raw.get("allowed_scripts", [])),
        "forbidden_actions": list(raw.get("forbidden_actions", [])),
        "mail_recipients_whitelist": list(raw.get("mail_recipients_whitelist", [])),
    }


def add_mail_recipient_to_whitelist(recipient: str, path: Path | None = None) -> list[str]:
    whitelist_path = path or DEFAULT_WHITELIST_PATH
    raw = _load_json(whitelist_path)
    recipients = list(raw.get("mail_recipients_whitelist", []))
    normalized_existing = {item.lower() for item in recipients}
    if recipient.lower() not in normalized_existing:
        recipients.append(recipient)
        raw["mail_recipients_whitelist"] = recipients
        whitelist_path.parent.mkdir(parents=True, exist_ok=True)
        with whitelist_path.open("w", encoding="utf-8") as handle:
            json.dump(raw, handle, ensure_ascii=False, indent=2)
    return recipients
