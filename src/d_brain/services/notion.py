"""Direct Notion API client for fast task creation and querying."""

from __future__ import annotations

import logging
from datetime import date

import httpx

logger = logging.getLogger(__name__)

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TASKS_DB_ID = "305289eb-342c-80ec-856d-f1c014cdff68"
PROJECTS_DB_ID = "305289eb-342c-808b-a075-fce6a56e22ce"

# Project name → Notion page ID (from "Проекты" database)
PROJECT_IDS: dict[str, str] = {
    "Контент-завод тексты": "305289eb-342c-8006-b59e-f5cc3156c7d8",
    "Организации и ассоциации": "305289eb-342c-801d-aa76-fb2c76b439ff",
    "Hubspot+Skillbox": "305289eb-342c-8022-9f4d-c627b3852e00",
    "Контент-завод видео": "305289eb-342c-8027-8f66-dcd90a486ea6",
    "Социальные сети": "305289eb-342c-802a-8e6e-fb2a4ec5d153",
    "Стратегия": "305289eb-342c-8046-a5f5-da9d87ea9012",
    "Маркетинговые материалы": "305289eb-342c-807c-91d4-d1c63b5b6a9a",
    "Zapusk International": "305289eb-342c-8085-920e-f362f112a740",
    "Мероприятия": "305289eb-342c-8096-ae8f-cbac8371998d",
    "Встречи и совещания": "305289eb-342c-8098-80f9-c8bab1a00270",
    "Лидогенерация": "305289eb-342c-80ce-babb-c87b1f0da95d",
    "СМИ": "305289eb-342c-80ed-b643-fb4d6dd71d82",
    "Запуск Энергосбыт": "305289eb-342c-80f1-b140-c755496996ce",
}


class NotionClient:
    """Thin async Notion client — only what the bot needs."""

    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def create_task(
        self,
        title: str,
        due_date: str | None = None,
        project: str | None = None,
    ) -> str:
        """Create a task in the Задачи и поручения database.

        Returns the URL of the created page.
        """
        properties: dict = {
            "Задача": {"title": [{"text": {"content": title}}]},
            "Status": {"status": {"name": "Not started"}},
        }
        if due_date:
            properties["Срок выполнения"] = {"date": {"start": due_date}}
        if project and project in PROJECT_IDS:
            properties["Проект"] = {"relation": [{"id": PROJECT_IDS[project]}]}

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
        limit: int = 50,
        project: str | None = None,
    ) -> list[dict]:
        """Query tasks from the database.

        query_type: "overdue" | "today" | "tomorrow" | "in_progress" | "all"
        project: optional project name to filter by "Проект" relation
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

        if project and project in PROJECT_IDS:
            project_page_id = PROJECT_IDS[project]
            project_filter = {"property": "Проект", "relation": {"contains": project_page_id}}
            if filters:
                filters = {"and": [filters, project_filter]}
            else:
                filters = project_filter

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

        data = resp.json()
        results = data.get("results", [])
        self._last_has_more = data.get("has_more", False)
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


def _format_tasks_reply(tasks: list[dict], query_type: str, project: str | None = None) -> str:
    """Format a list of tasks into Telegram HTML."""
    label = _QUERY_LABELS.get(query_type, "📋 Задачи")
    if project:
        label = f"📁 {project} — {label.split(' ', 1)[-1]}"

    if not tasks:
        return f"{label}\n\nЗадач нет 🎉"

    lines = [f"<b>{label}:</b>"]
    for t in tasks:
        name = t["name"]
        due = f" <i>({t['due_date']})</i>" if t.get("due_date") else ""
        status = f" [{t['status']}]" if t.get("status") and query_type == "all" else ""
        lines.append(f"• {name}{due}{status}")

    lines.append(f"\n<i>Всего: {len(tasks)}</i>")
    return "\n".join(lines)
