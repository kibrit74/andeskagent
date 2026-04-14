"""WebSocket canli ekran paylasimi: /ws/screen."""
from __future__ import annotations

import asyncio
import base64
import io
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["screen-stream"])


async def _capture_frame(*, quality: int = 40, scale: float = 0.5) -> tuple[bytes, int, int, float, int, int, int, int, int, int]:
    """Ekrani yakala, kucult ve JPEG byte'larina donustur."""
    from PIL import ImageGrab, Image

    loop = asyncio.get_running_loop()

    def _grab() -> tuple[bytes, int, int, float, int, int, int, int, int, int]:
        try:
            import ctypes

            user32 = ctypes.windll.user32
            virtual_x = int(user32.GetSystemMetrics(76))
            virtual_y = int(user32.GetSystemMetrics(77))
            virtual_width = int(user32.GetSystemMetrics(78))
            virtual_height = int(user32.GetSystemMetrics(79))
            cursor_width = int(user32.GetSystemMetrics(0))
            cursor_height = int(user32.GetSystemMetrics(1))

            screenshot = ImageGrab.grab(all_screens=True)
            if virtual_width and virtual_height:
                if screenshot.width != virtual_width or screenshot.height != virtual_height:
                    try:
                        screenshot = ImageGrab.grab(
                            bbox=(
                                virtual_x,
                                virtual_y,
                                virtual_x + virtual_width,
                                virtual_y + virtual_height,
                            ),
                            all_screens=True,
                        )
                    except Exception:
                        pass
        except OSError:
            # Masaustu oturumu yoksa bos frame don
            return b"", 0, 0, scale, 0, 0, 0, 0, 0, 0

        full_width, full_height = screenshot.width, screenshot.height
        try:
            cursor_width
            cursor_height
            virtual_x
            virtual_y
            virtual_width
            virtual_height
        except NameError:
            cursor_width = full_width
            cursor_height = full_height
            virtual_x = 0
            virtual_y = 0
            virtual_width = full_width
            virtual_height = full_height

        if scale != 1.0:
            new_size = (int(screenshot.width * scale), int(screenshot.height * scale))
            screenshot = screenshot.resize(new_size, Image.LANCZOS)

        buffer = io.BytesIO()
        screenshot.save(buffer, format="JPEG", quality=quality, optimize=True)
        return (
            buffer.getvalue(),
            full_width,
            full_height,
            scale,
            cursor_width,
            cursor_height,
            virtual_x,
            virtual_y,
            virtual_width,
            virtual_height,
        )

    return await loop.run_in_executor(None, _grab)


@router.websocket("/ws/screen")
async def screen_stream(websocket: WebSocket) -> None:
    """Canli ekran frame'lerini WebSocket uzerinden gonderir (~2 FPS)."""
    await websocket.accept()
    try:
        while True:
            frame_bytes, screen_w, screen_h, scale, cursor_w, cursor_h, virtual_x, virtual_y, virtual_w, virtual_h = await _capture_frame(
                quality=80,
                scale=1.0,
            )
            if frame_bytes:
                frame_b64 = base64.b64encode(frame_bytes).decode("ascii")
                await websocket.send_json({
                    "type": "frame",
                    "data": frame_b64,
                    "screen_width": screen_w,
                    "screen_height": screen_h,
                    "cursor_width": cursor_w,
                    "cursor_height": cursor_h,
                    "virtual_x": virtual_x,
                    "virtual_y": virtual_y,
                    "virtual_width": virtual_w,
                    "virtual_height": virtual_h,
                    "scale": scale,
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
