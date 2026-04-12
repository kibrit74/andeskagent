from __future__ import annotations

from pathlib import Path
import socket
import subprocess

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response


router = APIRouter(tags=["web"])

BASE_DIR = Path(__file__).resolve().parents[2]
ROOT_INDEX = BASE_DIR / "index.html"
MOBILE_DIR = BASE_DIR / "mobile-cli"
MOBILE_INDEX = MOBILE_DIR / "index.html"
QR_SCRIPT = BASE_DIR / "scripts" / "render_qr.mjs"


def _detect_lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        address = sock.getsockname()[0]
        return address if address and not address.startswith("127.") else None
    except OSError:
        return None
    finally:
        sock.close()


def _public_base_url(request: Request) -> str:
    current = request.url
    host = current.hostname or "127.0.0.1"
    port = current.port or (443 if current.scheme == "https" else 80)
    if host in {"127.0.0.1", "localhost"}:
        host = _detect_lan_ip() or host
    default_port = 443 if current.scheme == "https" else 80
    port_suffix = f":{port}" if port != default_port else ""
    return f"{current.scheme}://{host}{port_suffix}"


def _safe_mobile_path(asset_path: str) -> Path:
    candidate = (MOBILE_DIR / asset_path).resolve()
    if not str(candidate).startswith(str(MOBILE_DIR.resolve())) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Dosya bulunamadi.")
    return candidate


@router.get("/", include_in_schema=False)
def home(request: Request) -> HTMLResponse:
    html = ROOT_INDEX.read_text(encoding="utf-8", errors="replace")
    target_url = f"{_public_base_url(request)}/mobile-cli/"
    replacement = f"const targetUrl = {target_url!r};"
    html = html.replace(
        "const targetUrl = new URL('/mobile-cli/', window.location.href).toString();",
        replacement,
    )
    return HTMLResponse(content=html)


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
