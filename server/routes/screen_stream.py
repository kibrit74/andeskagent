"""WebSocket canli ekran paylasimi: /ws/screen."""
from __future__ import annotations

import asyncio
import base64
import io
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["screen-stream"])


async def _capture_frame(*, quality: int = 40, scale: float = 0.5) -> bytes:
    """Ekrani yakala, kucult ve JPEG byte'larina donustur."""
    from PIL import ImageGrab, Image

    loop = asyncio.get_running_loop()

    def _grab() -> bytes:
        try:
            screenshot = ImageGrab.grab()
        except OSError:
            # Masaustu oturumu yoksa bos frame don
            return b""

        if scale != 1.0:
            new_size = (int(screenshot.width * scale), int(screenshot.height * scale))
            screenshot = screenshot.resize(new_size, Image.LANCZOS)

        buffer = io.BytesIO()
        screenshot.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()

    return await loop.run_in_executor(None, _grab)


@router.websocket("/ws/screen")
async def screen_stream(websocket: WebSocket) -> None:
    """Canli ekran frame'lerini WebSocket uzerinden gonderir (~2 FPS)."""
    await websocket.accept()
    try:
        while True:
            frame_bytes = await _capture_frame(quality=40, scale=0.5)
            if frame_bytes:
                frame_b64 = base64.b64encode(frame_bytes).decode("ascii")
                await websocket.send_json({
                    "type": "frame",
                    "data": frame_b64,
                    "ts": time.time(),
                })
            await asyncio.sleep(0.5)  # ~2 FPS
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
