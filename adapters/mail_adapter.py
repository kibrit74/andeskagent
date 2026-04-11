from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


from core.errors import BrowserAuthError, BrowserStateError

BASE_DIR = Path(__file__).resolve().parent.parent
PLAYWRIGHT_SCRIPT_PATH = BASE_DIR / "scripts" / "send-mail-playwright.mjs"


@dataclass(slots=True)
class MailSendResult:
    sent_to: list[str]
    subject: str


class BrowserMailAdapter:
    def __init__(
        self,
        *,
        browser_channel: str = "msedge",
        user_data_dir: str = "data/playwright-edge-profile",
        mail_url: str = "https://mail.google.com/mail/u/0/#inbox",
        headless: bool = False,
        allowed_recipients: Iterable[str] | None = None,
    ) -> None:
        self.browser_channel = browser_channel
        self.user_data_dir = str((BASE_DIR / user_data_dir).resolve())
        self.mail_url = mail_url
        self.headless = headless
        self.allowed_recipients = {recipient.lower() for recipient in allowed_recipients or []}

    def _assert_recipient_allowed(self, recipients: list[str]) -> None:
        if not self.allowed_recipients:
            return
        for recipient in recipients:
            if recipient.lower() not in self.allowed_recipients:
                raise PermissionError(f"Recipient not in whitelist: {recipient}")

    def send(
        self,
        *,
        to: Iterable[str],
        subject: str,
        body: str,
        attachments: Iterable[Path] | None = None,
        sender: str | None = None,
    ) -> MailSendResult:
        recipients = [item.strip() for item in to if item and item.strip()]
        if not recipients:
            raise ValueError("At least one recipient is required")
        self._assert_recipient_allowed(recipients)

        attachment_paths = [str(Path(item).resolve()) for item in (attachments or [])]
        for attachment_path in attachment_paths:
            if not Path(attachment_path).exists():
                raise ValueError(f"Attachment not found: {attachment_path}")

        payload = {
            "to": recipients,
            "subject": subject,
            "body": body,
            "attachments": attachment_paths,
            "browserChannel": self.browser_channel,
            "userDataDir": self.user_data_dir,
            "mailUrl": self.mail_url,
            "headless": self.headless,
            "sender": sender or "",
        }

        completed = subprocess.run(
            ["node", str(PLAYWRIGHT_SCRIPT_PATH), json.dumps(payload, ensure_ascii=False)],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "Browser mail send failed."
            raise RuntimeError(message)

        stdout = completed.stdout.strip()
        if not stdout:
            raise RuntimeError("Browser mail send did not return a result.")

        try:
            result = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Browser mail send returned invalid JSON: {stdout}") from exc
            
        status = result.get("status")
        if status == "auth_required":
            raise BrowserAuthError(
                message=result.get("message", "Browser auth required"),
                code=result.get("code", "AUTH_REQUIRED")
            )
        elif status == "session_error" or status == "error":
            raise BrowserStateError(
                message=result.get("message", "Browser session error"),
                code=result.get("code", "SESSION_ERROR")
            )

        return MailSendResult(
            sent_to=list(result.get("sent_to", recipients)),
            subject=str(result.get("subject", subject)),
        )


def send_email_with_attachment(
    recipient: str,
    subject: str,
    body: str,
    file_path: str,
    *,
    host: str,
    port: int,
    username: str = "",
    password: str = "",
    use_tls: bool = True,
    sender: str = "",
    allowed_recipients: Iterable[str] | None = None,
    mail_transport: str = "playwright",
    browser_channel: str = "msedge",
    user_data_dir: str = "data/playwright-edge-profile",
    mail_url: str = "https://mail.google.com/mail/u/0/#inbox",
    headless: bool = False,
) -> MailSendResult:
    if mail_transport != "playwright":
        raise ValueError("Only playwright mail transport is supported in the current configuration.")

    adapter = BrowserMailAdapter(
        browser_channel=browser_channel,
        user_data_dir=user_data_dir,
        mail_url=mail_url,
        headless=headless,
        allowed_recipients=allowed_recipients,
    )
    return adapter.send(
        to=[recipient],
        subject=subject,
        body=body,
        attachments=[Path(file_path)],
        sender=sender or username or None,
    )
