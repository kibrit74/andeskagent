from contextlib import asynccontextmanager

from fastapi import FastAPI

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


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = load_settings()
    configure_logging(settings.log_path)
    init_db(settings.sqlite_path)
    get_logger().info("application_started")
    yield


app = FastAPI(
    title="AI Destekli Teknik Destek Ajanı",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(system_router)
app.include_router(web_router)
app.include_router(files_router)
app.include_router(mail_router)
app.include_router(scripts_router)
app.include_router(command_router)
app.include_router(command_ui_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
