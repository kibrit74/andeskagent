from __future__ import annotations

from pathlib import Path
import subprocess

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response


router = APIRouter(tags=["web"])

BASE_DIR = Path(__file__).resolve().parents[2]
ROOT_INDEX = BASE_DIR / "index.html"
MOBILE_DIR = BASE_DIR / "mobile-cli"
MOBILE_INDEX = MOBILE_DIR / "index.html"
QR_SCRIPT = BASE_DIR / "scripts" / "render_qr.mjs"


def _safe_mobile_path(asset_path: str) -> Path:
    candidate = (MOBILE_DIR / asset_path).resolve()
    if not str(candidate).startswith(str(MOBILE_DIR.resolve())) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Dosya bulunamadi.")
    return candidate


@router.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(ROOT_INDEX)


@router.get("/mobile-cli", include_in_schema=False)
@router.get("/mobile-cli/", include_in_schema=False)
def mobile_home() -> FileResponse:
    return FileResponse(MOBILE_INDEX)


@router.get("/mobile-cli/{asset_path:path}", include_in_schema=False)
def mobile_asset(asset_path: str) -> FileResponse:
    return FileResponse(_safe_mobile_path(asset_path))


@router.get("/qr.svg", include_in_schema=False)
def qr_svg(target: str = Query(..., min_length=1, max_length=2048)) -> Response:
    if not target.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Gecersiz hedef adresi.")

    try:
        result = subprocess.run(
            ["node", str(QR_SCRIPT), target],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.stderr.strip() or "QR uretilemedi.") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="QR uretimi zaman asimina ugradi.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(content=result.stdout, media_type="image/svg+xml")
