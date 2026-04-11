from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from adapters.mail_adapter import send_email_with_attachment
from core.auth import bearer_token_dependency
from core.config import add_mail_recipient_to_whitelist, load_settings
from db import log_task


settings = load_settings()
router = APIRouter(
    prefix="/files",
    tags=["mail"],
    dependencies=[Depends(bearer_token_dependency(settings.bearer_token))],
)


class SendFileRequest(BaseModel):
    file_path: str
    to: EmailStr
    subject: str = "AI Destekli Teknik Destek Ajani"
    body: str = "Istenen dosya ektedir."


@router.post("/send")
def send_file(request: SendFileRequest) -> dict[str, str]:
    try:
        settings.mail_recipients_whitelist = add_mail_recipient_to_whitelist(str(request.to))
        send_email_with_attachment(
            recipient=request.to,
            subject=request.subject,
            body=request.body,
            file_path=request.file_path,
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            sender=settings.default_mail_from,
            allowed_recipients=settings.mail_recipients_whitelist,
            mail_transport=settings.mail_transport,
            browser_channel=settings.playwright_browser_channel,
            user_data_dir=settings.playwright_user_data_dir,
            mail_url=settings.playwright_mail_url,
            headless=settings.playwright_headless,
        )
        log_task(
            settings.sqlite_path,
            task_type="files_send",
            status="success",
            input_text=request.file_path,
            output_text=str(request.to),
        )
        return {"status": "sent"}
    except (ValueError, PermissionError) as error:
        log_task(
            settings.sqlite_path,
            task_type="files_send",
            status="blocked",
            input_text=request.file_path,
            output_text=str(error),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
