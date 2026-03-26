"""Google Calendar integration service.

Fetches events via Calendar API, formats for Telegram display.

Usage:
    # One-time OAuth setup (run locally with browser):
    python -m d_brain.services.calendar --setup

    # In bot code:
    client = CalendarClient("gcp-oauth.keys.json", "calendar-token.json")
    events = client.fetch_events(days=1)
    text = client.format_events_html(events)
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class CalendarClient:
    """Fetch and format events from Google Calendar API."""

    def __init__(self, credentials_path: str, token_path: str) -> None:
        self._credentials_path = Path(credentials_path)
        self._token_path = Path(token_path)
        self._service: Any = None

    @property
    def enabled(self) -> bool:
        """Check if Calendar token exists and is usable."""
        return self._token_path.exists()

    def _get_service(self) -> Any:
        """Build (or reuse) an authenticated Calendar API service."""
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
            logger.info("Calendar token refreshed")

        if not creds or not creds.valid:
            raise RuntimeError(
                "Calendar token missing or invalid. "
                "Run: python -m d_brain.services.calendar --setup"
            )

        if creds and not creds.quota_project_id:
            creds = creds.with_quota_project("d-brain-489019")

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def fetch_events(
        self,
        days: int = 1,
        max_results: int = 20,
        calendar_id: str = "primary",
    ) -> list[dict[str, Any]]:
        """Fetch upcoming events for the next N days.

        Each dict: {id, summary, start, end, location, description, all_day, calendar}
        """
        service = self._get_service()

        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).replace(
            hour=23, minute=59, second=59
        ).isoformat()

        try:
            resp = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except Exception:
            logger.exception("Calendar API list failed")
            return []

        raw_events = resp.get("items", [])
        events: list[dict[str, Any]] = []
        for ev in raw_events:
            events.append(self._parse_event(ev))
        return events

    def fetch_all_calendars_events(
        self,
        days: int = 1,
        max_results: int = 30,
    ) -> list[dict[str, Any]]:
        """Fetch events from all visible calendars."""
        service = self._get_service()

        try:
            cal_list = service.calendarList().list().execute()
        except Exception:
            logger.exception("Calendar list failed")
            return self.fetch_events(days=days, max_results=max_results)

        all_events: list[dict[str, Any]] = []
        for cal in cal_list.get("items", []):
            cal_id = cal["id"]
            cal_name = cal.get("summary", cal_id)
            events = self.fetch_events(
                days=days, max_results=max_results, calendar_id=cal_id
            )
            for ev in events:
                ev["calendar"] = cal_name
            all_events.extend(events)

        all_events.sort(key=lambda e: e.get("start_sort", ""))
        return all_events

    def _parse_event(self, ev: dict[str, Any]) -> dict[str, Any]:
        """Extract key fields from a Calendar API event resource."""
        start_raw = ev.get("start", {})
        end_raw = ev.get("end", {})

        all_day = "date" in start_raw
        start_str = start_raw.get("dateTime", start_raw.get("date", ""))
        end_str = end_raw.get("dateTime", end_raw.get("date", ""))

        # Format time for display
        if all_day:
            start_display = start_str
            start_sort = start_str + "T00:00:00"
        else:
            try:
                dt = datetime.fromisoformat(start_str)
                start_display = dt.strftime("%H:%M")
                start_sort = start_str
            except (ValueError, TypeError):
                start_display = start_str
                start_sort = start_str

        if not all_day and end_str:
            try:
                dt_end = datetime.fromisoformat(end_str)
                end_display = dt_end.strftime("%H:%M")
            except (ValueError, TypeError):
                end_display = end_str
        else:
            end_display = ""

        return {
            "id": ev.get("id", ""),
            "summary": ev.get("summary", "(без названия)"),
            "start": start_display,
            "end": end_display,
            "start_sort": start_sort,
            "location": ev.get("location", ""),
            "description": (ev.get("description") or "")[:200],
            "all_day": all_day,
            "calendar": "",
            "hangout_link": ev.get("hangoutLink", ""),
        }

    def format_events_html(self, events: list[dict[str, Any]], title: str = "Календарь") -> str:
        """Format events as Telegram HTML."""
        if not events:
            return f"📅 <b>{title}</b>\n\nСобытий нет."

        lines = [f"📅 <b>{title} ({len(events)})</b>\n"]

        for ev in events:
            if ev["all_day"]:
                time_str = "весь день"
            else:
                time_str = f"{ev['start']}–{ev['end']}" if ev["end"] else ev["start"]

            line = f"• <b>{time_str}</b> — {ev['summary']}"
            if ev["location"]:
                line += f"\n  📍 {ev['location'][:40]}"
            if ev["hangout_link"]:
                line += "\n  🔗 Google Meet"
            lines.append(line)

        return "\n".join(lines)

    def format_for_briefing(self, events: list[dict[str, Any]]) -> str:
        """Short format for morning briefing inclusion."""
        if not events:
            return "Событий на сегодня нет."

        lines = [f"=== КАЛЕНДАРЬ ({len(events)} событий) ===\n"]
        for ev in events:
            if ev["all_day"]:
                time_str = "весь день"
            else:
                time_str = f"{ev['start']}–{ev['end']}" if ev["end"] else ev["start"]
            line = f"- {time_str}: {ev['summary']}"
            if ev["location"]:
                line += f" ({ev['location'][:30]})"
            lines.append(line)
        lines.append("=== КОНЕЦ КАЛЕНДАРЯ ===")
        return "\n".join(lines)

    @staticmethod
    def setup_oauth(
        token_path: str = "calendar-token.json",
        credentials_path: str = "gcp-oauth.keys.json",
        quota_project: str = "d-brain-489019",
    ) -> None:
        """Run interactive OAuth flow (needs browser). One-time setup."""
        import json

        creds_file = Path(credentials_path)
        if creds_file.exists():
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
        else:
            raise FileNotFoundError(
                f"Credentials file not found: {credentials_path}. "
                "Download it from GCP Console."
            )
        creds = flow.run_local_server(port=0)
        token_data = json.loads(creds.to_json())
        token_data["quota_project_id"] = quota_project
        Path(token_path).write_text(json.dumps(token_data, indent=2))
        print(f"✅ Calendar token saved to {token_path}")


if __name__ == "__main__":
    if "--setup" in sys.argv:
        CalendarClient.setup_oauth()
    else:
        print("Usage: python -m d_brain.services.calendar --setup")
