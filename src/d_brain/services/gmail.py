"""Gmail integration service.

Fetches emails via Gmail API, formats them for Claude analysis
and Telegram display.

Usage:
    # One-time OAuth setup (run locally with browser):
    python -m d_brain.services.gmail --setup

    # In bot code:
    client = GmailClient("gcp-oauth.keys.json", "gmail-token.json")
    emails = client.fetch_emails(hours=24)
    text = client.format_for_claude(emails)
"""

from __future__ import annotations

import base64
import logging
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailClient:
    """Fetch and format emails from Gmail API."""

    def __init__(self, credentials_path: str, token_path: str) -> None:
        self._credentials_path = Path(credentials_path)
        self._token_path = Path(token_path)
        self._service: Any = None

    @property
    def enabled(self) -> bool:
        """Check if Gmail token exists and is usable."""
        return self._token_path.exists()

    def _get_service(self) -> Any:
        """Build (or reuse) an authenticated Gmail API service."""
        if self._service is not None:
            return self._service

        creds: Credentials | None = None

        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._token_path), SCOPES
            )

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._token_path.write_text(creds.to_json())
            logger.info("Gmail token refreshed")

        if not creds or not creds.valid:
            raise RuntimeError(
                "Gmail token missing or invalid. "
                "Run: python -m d_brain.services.gmail --setup"
            )

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def fetch_emails(
        self,
        hours: int = 24,
        unread_only: bool = True,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch recent emails and return structured dicts.

        Each dict: {id, from_name, from_email, subject, snippet, date, body_preview}
        """
        service = self._get_service()
        after_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
        query = f"after:{after_ts}"
        if unread_only:
            query += " is:unread"

        try:
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
        except Exception:
            logger.exception("Gmail API list failed")
            return []

        message_ids = resp.get("messages", [])
        if not message_ids:
            return []

        emails: list[dict[str, Any]] = []
        for msg_ref in message_ids:
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_ref["id"], format="full")
                    .execute()
                )
                emails.append(self._parse_message(msg))
            except Exception:
                logger.warning("Failed to fetch message %s", msg_ref["id"])

        return emails

    def _parse_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Extract key fields from a Gmail API message resource."""
        headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}

        from_raw = headers.get("from", "")
        from_name, from_email = parseaddr(from_raw)
        if not from_name:
            from_name = from_email

        date_str = headers.get("date", "")
        subject = headers.get("subject", "(без темы)")
        snippet = msg.get("snippet", "")

        body_preview = self._extract_body(msg["payload"])

        return {
            "id": msg["id"],
            "from_name": from_name,
            "from_email": from_email,
            "subject": subject,
            "snippet": snippet,
            "date": date_str,
            "body_preview": body_preview[:1000],
        }

    def _extract_body(self, payload: dict[str, Any]) -> str:
        """Extract plain-text body from MIME payload."""
        # Direct body (simple message)
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        # Multipart — look for text/plain
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

        # Nested multipart (e.g. multipart/alternative inside multipart/mixed)
        for part in payload.get("parts", []):
            for sub in part.get("parts", []):
                if sub.get("mimeType") == "text/plain" and sub.get("body", {}).get("data"):
                    return base64.urlsafe_b64decode(sub["body"]["data"]).decode("utf-8", errors="replace")

        return ""

    def format_for_claude(self, emails: list[dict[str, Any]]) -> str:
        """Format emails as structured text for Claude prompt injection."""
        if not emails:
            return "Новых писем нет."

        lines = [f"=== ВХОДЯЩАЯ ПОЧТА ({len(emails)} писем) ===\n"]
        for i, e in enumerate(emails, 1):
            lines.append(
                f"--- Письмо {i} ---\n"
                f"От: {e['from_name']} <{e['from_email']}>\n"
                f"Тема: {e['subject']}\n"
                f"Дата: {e['date']}\n"
                f"Текст:\n{e['body_preview']}\n"
            )
        lines.append("=== КОНЕЦ ПОЧТЫ ===")
        return "\n".join(lines)

    def format_summary_html(self, emails: list[dict[str, Any]]) -> str:
        """Format emails as Telegram HTML for quick preview."""
        if not emails:
            return "📧 Новых писем нет."

        lines = [f"📧 <b>Почта ({len(emails)})</b>\n"]
        for e in emails[:10]:
            subj = e["subject"][:60]
            sender = e["from_name"][:25]
            lines.append(f"• <b>{sender}</b>: {subj}")

        if len(emails) > 10:
            lines.append(f"\n...и ещё {len(emails) - 10}")
        return "\n".join(lines)

    @staticmethod
    def setup_oauth(credentials_path: str, token_path: str) -> None:
        """Run interactive OAuth flow (needs browser). One-time setup."""
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
        creds = flow.run_local_server(port=0)
        Path(token_path).write_text(creds.to_json())
        print(f"✅ Gmail token saved to {token_path}")
        print(f"   Copy to VPS: scp {token_path} root@<VPS>:/path/to/project/")


if __name__ == "__main__":
    if "--setup" in sys.argv:
        creds_path = sys.argv[sys.argv.index("--setup") + 1] if len(sys.argv) > sys.argv.index("--setup") + 1 else "gcp-oauth.keys.json"
        token_out = "gmail-token.json"
        GmailClient.setup_oauth(creds_path, token_out)
    else:
        print("Usage: python -m d_brain.services.gmail --setup [credentials.json]")
