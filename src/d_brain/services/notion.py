"""Direct Notion API client for fast task creation."""

import logging

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
            "Name": {"title": [{"text": {"content": title}}]},
            "Status": {"status": {"name": "Not started"}},
        }
        if due_date:
            properties["Due date"] = {"date": {"start": due_date}}

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
