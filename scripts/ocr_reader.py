from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from PIL import Image
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine


def _build_bitmap(image_path: Path) -> SoftwareBitmap:
    image = Image.open(image_path).convert("RGBA")
    bitmap = SoftwareBitmap(
        BitmapPixelFormat.BGRA8,
        image.width,
        image.height,
        BitmapAlphaMode.PREMULTIPLIED,
    )
    bitmap.copy_from_buffer(bytearray(image.tobytes("raw", "BGRA")))
    return bitmap


async def _recognize_text(image_path: Path, language_tag: str) -> dict[str, object]:
    bitmap = _build_bitmap(image_path)
    engine = OcrEngine.try_create_from_language(Language(language_tag))
    if engine is None:
        raise RuntimeError(f"OCR engine unavailable for language '{language_tag}'.")

    result = await engine.recognize_async(bitmap)
    lines = [line.text.strip() for line in result.lines if line.text and line.text.strip()]
    return {
        "ocr_available": True,
        "language": engine.recognizer_language.language_tag,
        "text": result.text.strip(),
        "lines": lines,
        "line_count": len(lines),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ocr_available": False, "error": "image_path gerekli."}))
        return 1

    image_path = Path(sys.argv[1]).expanduser().resolve()
    language_tag = sys.argv[2] if len(sys.argv) > 2 else "tr"
    if not image_path.exists():
        print(json.dumps({"ocr_available": False, "error": f"Gorsel bulunamadi: {image_path}"}))
        return 1

    try:
        payload = asyncio.run(_recognize_text(image_path, language_tag))
    except Exception as exc:
        print(json.dumps({"ocr_available": False, "error": str(exc)}))
        return 1

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
