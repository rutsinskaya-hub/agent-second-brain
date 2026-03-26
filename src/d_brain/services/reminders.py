"""In-memory reminder scheduler with JSON persistence.

Reminders survive bot restarts via a JSON file.
Uses asyncio tasks — no external dependencies needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

MOSCOW_TZ = timezone(timedelta(hours=3))


class Reminder:
    """Single reminder entry."""

    def __init__(
        self,
        reminder_id: str,
        chat_id: int,
        text: str,
        fire_at: datetime,
        created_at: datetime | None = None,
    ) -> None:
        self.id = reminder_id
        self.chat_id = chat_id
        self.text = text
        self.fire_at = fire_at
        self.created_at = created_at or datetime.now(MOSCOW_TZ)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "text": self.text,
            "fire_at": self.fire_at.isoformat(),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Reminder:
        return cls(
            reminder_id=data["id"],
            chat_id=data["chat_id"],
            text=data["text"],
            fire_at=datetime.fromisoformat(data["fire_at"]),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


# Type for the callback: async func(chat_id, text) -> None
SendCallback = Callable[[int, str], Coroutine[Any, Any, None]]


class ReminderScheduler:
    """Schedule and fire reminders using asyncio tasks."""

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path
        self._reminders: dict[str, Reminder] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._send_callback: SendCallback | None = None
        self._load()

    def set_callback(self, callback: SendCallback) -> None:
        """Set the async callback for sending reminder messages."""
        self._send_callback = callback

    def add(self, chat_id: int, text: str, fire_at: datetime) -> Reminder:
        """Add a new reminder and schedule it."""
        reminder = Reminder(
            reminder_id=str(uuid.uuid4())[:8],
            chat_id=chat_id,
            text=text,
            fire_at=fire_at,
        )
        self._reminders[reminder.id] = reminder
        self._save()
        self._schedule(reminder)
        logger.info("Reminder added: %s at %s — %s", reminder.id, fire_at, text[:40])
        return reminder

    def remove(self, reminder_id: str) -> bool:
        """Cancel and remove a reminder."""
        if reminder_id not in self._reminders:
            return False
        task = self._tasks.pop(reminder_id, None)
        if task and not task.done():
            task.cancel()
        del self._reminders[reminder_id]
        self._save()
        return True

    def list_active(self, chat_id: int | None = None) -> list[Reminder]:
        """List upcoming reminders, optionally filtered by chat."""
        now = datetime.now(MOSCOW_TZ)
        result = [
            r for r in self._reminders.values()
            if r.fire_at > now and (chat_id is None or r.chat_id == chat_id)
        ]
        result.sort(key=lambda r: r.fire_at)
        return result

    def start_all(self) -> int:
        """Schedule all loaded reminders. Call after setting callback. Returns count."""
        count = 0
        expired_ids: list[str] = []
        now = datetime.now(MOSCOW_TZ)

        for r in self._reminders.values():
            if r.fire_at <= now:
                expired_ids.append(r.id)
            else:
                self._schedule(r)
                count += 1

        # Clean up expired
        for rid in expired_ids:
            del self._reminders[rid]
        if expired_ids:
            self._save()
            logger.info("Cleaned up %d expired reminders", len(expired_ids))

        return count

    def _schedule(self, reminder: Reminder) -> None:
        """Create an asyncio task to fire the reminder."""
        now = datetime.now(MOSCOW_TZ)
        delay = (reminder.fire_at - now).total_seconds()
        if delay <= 0:
            return

        task = asyncio.create_task(self._fire_after(reminder, delay))
        self._tasks[reminder.id] = task

    async def _fire_after(self, reminder: Reminder, delay: float) -> None:
        """Wait and then fire the reminder."""
        try:
            await asyncio.sleep(delay)
            if self._send_callback:
                await self._send_callback(reminder.chat_id, reminder.text)
                logger.info("Reminder fired: %s — %s", reminder.id, reminder.text[:40])
            # Clean up
            self._reminders.pop(reminder.id, None)
            self._tasks.pop(reminder.id, None)
            self._save()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error firing reminder %s", reminder.id)

    def _save(self) -> None:
        """Persist reminders to JSON."""
        data = [r.to_dict() for r in self._reminders.values()]
        self._storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load(self) -> None:
        """Load reminders from JSON."""
        if not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text())
            for item in data:
                r = Reminder.from_dict(item)
                self._reminders[r.id] = r
            logger.info("Loaded %d reminders from disk", len(self._reminders))
        except Exception:
            logger.exception("Failed to load reminders")
