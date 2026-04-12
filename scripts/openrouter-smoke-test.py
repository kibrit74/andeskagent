from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=BASE_DIR / ".env")
except Exception:
    pass

from adapters.openrouter_adapter import parse_command_with_openrouter
from core.config import load_settings


def _mask(value: str) -> str:
    if not value:
        return ""
    return value[:6] + "..." + value[-4:] if len(value) > 12 else "***"


def _run_smoke(*, api_key: str, model: str) -> dict[str, Any]:
    prompt = (
        "Komut: masaustundeki rapor dosyasini bul\n"
        "Cevap formatı: {\"action\":\"search_file\",\"params\":{\"query\":\"rapor\",\"location\":\"desktop\"},\"confidence\":0.9}\n"
        "Kurallar: SADECE JSON don, ekstra metin yazma."
    )
    payload = parse_command_with_openrouter(api_key=api_key, model=model, prompt=prompt)
    return {
        "action": payload.action,
        "params": payload.params,
        "confidence": payload.confidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenRouter smoke test")
    parser.add_argument("--api-key", default=os.environ.get("OPENROUTER_API_KEY", ""))
    parser.add_argument("--model", default=os.environ.get("OPENROUTER_MODEL", ""))
    args = parser.parse_args()

    settings = load_settings()
    api_key = args.api_key or settings.openrouter_api_key
    model = args.model or settings.openrouter_model

    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY bulunamadi.")
    if not model:
        raise SystemExit("OPENROUTER_MODEL bulunamadi.")

    print(json.dumps({"api_key": _mask(api_key), "model": model}, ensure_ascii=False))
    result = _run_smoke(api_key=api_key, model=model)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
