from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.command_parser import parse_command
from core.config import AppSettings


SCENARIOS: list[str] = [
    "masaustundeki excel dosyalarini bul",
    "masa ütünde ki excel dosyalarini bul",
    "masaustune yeni klasor olustur",
    "Tüm excelleri 2026 exceller isminde bir klasör oluşturup o klasöre taşı",
    "tum excel dosyalarini 2026 exceller isminde bir klasor olusturup o klasore tasi",
    "2026 exceller klasörünü ziple",
    "2026 exceller (2) klasörünü ziple",
    "2026 exceller klasorunu arsivle",
    "masaustundeki tum pdfleri Arsiv isminde klasor olusturup icine kopyala",
    "masaustumdeki raporu downloads klasorune tasi",
    "masaustumdeki raporu documents klasorune tasi",
    "downloadsdaki raporu masaustune tasi",
    "documentsdaki raporu masaustune tasi",
    "Indirim Maili excelini yavuzob@gmail.com adresine gonder",
    "en son excel dosyasini ali@example.com adresine gonder",
    "outlooku ac",
    "gorunen pencereleri listele",
    "chrome penceresini bekle",
    "Outlook'ta Gonder butonuna tikla",
    "ekrani oku",
    "ekran goruntusu al",
]


def main() -> None:
    settings = AppSettings()
    print(f"{'#':<3} {'Action':<16} {'Conf':<5} {'Params'}")
    print("-" * 110)
    for index, text in enumerate(SCENARIOS, 1):
        parsed = parse_command(text, settings)
        print(f"{index:<3} {parsed.action:<16} {parsed.confidence:<5.2f} {parsed.params}")
        print(f"    {text}")


if __name__ == "__main__":
    main()
