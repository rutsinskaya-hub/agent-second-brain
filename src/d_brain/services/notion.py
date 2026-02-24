"""Direct Notion API client for fast task creation and querying."""

from __future__ import annotations

import logging
from datetime import date

import httpx

logger = logging.getLogger(__name__)

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TASKS_DB_ID = "305289eb-342c-80ec-856d-f1c014cdff68"


class NotionClient:
    """Thin async Notion client — only what the bot needs."""

    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def create_task(self, title: str, due_date: str | None = None) -> str:
        """Create a task in the Задачи и поручения database.

        Returns the URL of the created page.
        """
        properties: dict = {
            "Задача": {"title": [{"text": {"content": title}}]},
            "Status": {"status": {"name": "Not started"}},
        }
        if due_date:
            properties["Срок выполнения"] = {"date": {"start": due_date}}

        payload = {
            "parent": {"database_id": TASKS_DB_ID},
            "properties": properties,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{NOTION_API_URL}/pages",
                headers=self._headers,
                json=payload,
            )

        if resp.status_code != 200:
            logger.error("Notion API error %s: %s", resp.status_code, resp.text)
            raise RuntimeError(f"Notion API вернул {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        return data.get("url", "")

    async def query_tasks(
        self,
        query_type: str = "all",
        limit: int = 10,
    ) -> list[dict]:
        """Query tasks from the database.

        query_type: "overdue" | "today" | "tomorrow" | "in_progress" | "all"
        Returns list of simplified task dicts: {name, status, due_date}
        """
        from datetime import timedelta
        today = date.today().isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        filters: dict = {}
        if query_type == "overdue":
            filters = {
                "and": [
                    {"property": "Срок выполнения", "date": {"before": today}},
                    {"property": "Status", "status": {"does_not_equal": "Done"}},
                ]
            }
        elif query_type == "today":
            filters = {"property": "Срок выполнения", "date": {"equals": today}}
        elif query_type == "tomorrow":
            filters = {"property": "Срок выполнения", "date": {"equals": tomorrow}}
        elif query_type == "in_progress":
            filters = {"property": "Status", "status": {"equals": "In progress"}}
        else:  # all — exclude Done
            filters = {"property": "Status", "status": {"does_not_equal": "Done"}}

        payload: dict = {
            "filter": filters,
            "sorts": [{"property": "Срок выполнения", "direction": "ascending"}],
            "page_size": limit,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{NOTION_API_URL}/databases/{TASKS_DB_ID}/query",
                headers=self._headers,
                json=payload,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"Notion API вернул {resp.status_code}: {resp.text[:200]}")

        results = resp.json().get("results", [])
        tasks = []
        for page in results:
            props = page.get("properties", {})
            # Extract task name — property is "Задача" (title type)
            title_prop = props.get("Задача", {})
            title_parts = title_prop.get("title", [])
            name = "".join(t.get("plain_text", "") for t in title_parts).strip()
            if not name:
                continue
            # Extract status
            status_prop = props.get("Status", {})
            status = status_prop.get("status", {}).get("name", "") if status_prop else ""
            # Extract due date — property is "Срок выполнения"
            due_prop = props.get("Срок выполнения", {})
            due_date = ""
            if due_prop and due_prop.get("date"):
                due_date = due_prop["date"].get("start", "")
            tasks.append({"name": name, "status": status, "due_date": due_date})
        return tasks


_QUERY_LABELS = {
    "overdue":     "🔴 Просроченные задачи",
    "today":       "📅 Задачи на сегодня",
    "tomorrow":    "📅 Задачи на завтра",
    "in_progress": "⏳ Задачи в процессе",
    "all":         "📋 Активные задачи",
}


def _format_tasks_reply(tasks: list[dict], query_type: str) -> str:
    """Format a list of tasks into Telegram HTML."""
    label = _QUERY_LABELS.get(query_type, "📋 Задачи")

    if not tasks:
        return f"{label}\n\nЗадач нет 🎉"

    lines = [f"<b>{label}:</b>"]
    for t in tasks:
        name = t["name"]
        due = f" <i>({t['due_date']})</i>" if t.get("due_date") else ""
        status = f" [{t['status']}]" if t.get("status") and query_type == "all" else ""
        lines.append(f"• {name}{due}{status}")

    if len(tasks) == 10:
        lines.append("<i>...показаны первые 10</i>")

    return "\n".join(lines)
