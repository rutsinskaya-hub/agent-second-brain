"""IMAP mail integration for daria@anko.team (reg.ru hosting).

Read-only mirror of GmailClient: fetches recent messages over IMAP,
formats them for Claude analysis and Telegram display. Never marks
messages as read and never deletes — the IMAP session is opened in
read-only mode and bodies are fetched with BODY.PEEK.

reg.ru defaults: host mail.hosting.reg.ru, IMAP SSL port 993, the
username is the full email address.

Usage:
    client = AnkoMailClient(host, port, user, password)
    emails = client.fetch_emails(hours=24)
    text = client.format_for_claude(emails)
"""

from __future__ import annotations

import email
import imaplib
import logging
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

logger = logging.getLogger(__name__)


class AnkoMailClient:
    """Fetch and format emails from an IMAP mailbox (read-only)."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        mailbox: str = "INBOX",
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._mailbox = mailbox

    @property
    def enabled(self) -> bool:
        """Usable only when host, user and password are all configured."""
        return bool(self._host and self._user and self._password)

    def _connect(self) -> imaplib.IMAP4_SSL:
        """Open an authenticated SSL IMAP connection."""
        conn = imaplib.IMAP4_SSL(self._host, self._port)
        conn.login(self._user, self._password)
        return conn

    def fetch_emails(
        self,
        hours: int = 24,
        unread_only: bool = True,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch recent emails and return structured dicts.

        Each dict: {id, from_name, from_email, subject, snippet, date, body_preview}
        """
        try:
            conn = self._connect()
        except Exception:
            logger.exception("IMAP login failed for %s", self._user)
            raise

        try:
            # readonly=True guarantees no flags (\Seen) are ever modified.
            conn.select(self._mailbox, readonly=True)

            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            # IMAP SINCE has day granularity; search with a one-day margin
            # and filter precisely by parsed date below.
            since = (cutoff - timedelta(days=1)).strftime("%d-%b-%Y")
            criteria = ["SINCE", since]
            if unread_only:
                criteria.insert(0, "UNSEEN")

            typ, data = conn.search(None, *criteria)
            if typ != "OK" or not data or not data[0]:
                return []

            uids = data[0].split()
            # Newest first, then cap.
            uids = list(reversed(uids))[: max_results * 2]

            emails: list[dict[str, Any]] = []
            for uid in uids:
                # BODY.PEEK[] fetches the full message WITHOUT setting \Seen.
                typ, msg_data = conn.fetch(uid, "(BODY.PEEK[])")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                parsed = self._parse_message(uid.decode(), email.message_from_bytes(raw))
                if parsed["_dt"] is not None and parsed["_dt"] < cutoff:
                    continue
                emails.append(parsed)
                if len(emails) >= max_results:
                    break

            for e in emails:
                e.pop("_dt", None)
            return emails
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    @staticmethod
    def _decode(value: str | None) -> str:
        """Decode RFC 2047 encoded-word headers (=?utf-8?...?=) to plain text."""
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    def _parse_message(self, uid: str, msg: Message) -> dict[str, Any]:
        """Extract key fields from a parsed email.message.Message."""
        from_raw = self._decode(msg.get("From", ""))
        from_name, from_email = parseaddr(from_raw)
        if not from_name:
            from_name = from_email

        subject = self._decode(msg.get("Subject")) or "(без темы)"

        date_raw = msg.get("Date", "")
        dt: datetime | None = None
        try:
            dt = parsedate_to_datetime(date_raw)
            if dt is not None and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = None

        body = self._extract_body(msg)
        snippet = " ".join(body.split())[:200]

        return {
            "id": uid,
            "from_name": from_name,
            "from_email": from_email,
            "subject": subject,
            "snippet": snippet,
            "date": date_raw,
            "body_preview": body[:1000],
            "_dt": dt,
        }

    def _extract_body(self, msg: Message) -> str:
        """Extract a plain-text body from a MIME message, preferring text/plain."""
        if not msg.is_multipart():
            return self._payload_text(msg)

        plain = ""
        html = ""
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp.lower():
                continue
            if ctype == "text/plain" and not plain:
                plain = self._payload_text(part)
            elif ctype == "text/html" and not html:
                html = self._payload_text(part)
        return plain or html

    @staticmethod
    def _payload_text(part: Message) -> str:
        """Decode a single part's payload to a string."""
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            return ""
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            return payload.decode("utf-8", errors="replace")

    def format_for_claude(self, emails: list[dict[str, Any]]) -> str:
        """Format emails as structured text for Claude prompt injection."""
        if not emails:
            return "Новых писем нет."

        lines = [f"=== ВХОДЯЩАЯ ПОЧТА ({len(emails)} писем) ===\n"]
        for i, e in enumerate(emails, 1):
            lines.append(
                f"--- Письмо {i} ---\n"
                f"ID: {e['id']}\n"
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
