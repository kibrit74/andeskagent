from contextlib import asynccontextmanager
import threading
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from adapters.desktop_adapter import prewarm_desktop_runtime
from core.config import load_settings
from core.logger import configure_logging, get_logger
from db import init_db
from server.routes.command import router as command_router
from server.routes.command import ui_router as command_ui_router
from server.routes.files import router as files_router
from server.routes.mail import router as mail_router
from server.routes.scripts import router as scripts_router
from server.routes.system import router as system_router
from server.routes.web import router as web_router
from server.routes.screen_stream import router as screen_stream_router
from server.routes.screen_control import router as screen_control_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = load_settings()
    configure_logging(settings.log_path)
    init_db(settings.sqlite_path)
    threading.Thread(target=prewarm_desktop_runtime, daemon=True).start()
    get_logger().info("application_started")
    yield


app = FastAPI(
    title="AI Destekli Teknik Destek Ajanı",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger = get_logger("teknikajan.http")
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"
    logger.debug(f"Incoming Request: {request.method} {request.url} from {client_ip}")
    
    response = await call_next(request)
    
    process_time = (time.time() - start_time) * 1000
    logger.debug(f"Outgoing Response: {request.method} {request.url} - Status {response.status_code} - Completed in {process_time:.2f}ms")
    
    return response

app.include_router(system_router)
app.include_router(web_router)
app.include_router(files_router)
app.include_router(mail_router)
app.include_router(scripts_router)
app.include_router(command_router)
app.include_router(command_ui_router)
app.include_router(screen_stream_router)
app.include_router(screen_control_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
