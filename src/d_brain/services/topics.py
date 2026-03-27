"""Forum Topics configuration and routing.

Each topic in a Telegram group gets its own:
- System prompt (personality/focus)
- Working directory (optional)
- MCP config (optional)

Config stored in vault/topics.json.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = """Ты - персональный ассистент d-brain.
Отвечай кратко и по делу. Формат: HTML для Telegram.
Допустимые теги: <b>, <i>, <code>, <s>, <u>.
НЕ используй markdown."""


@dataclass
class TopicConfig:
    """Configuration for a single forum topic."""
    topic_id: int
    name: str
    prompt: str = DEFAULT_PROMPT
    cwd: str = ""  # empty = use default vault parent
    mcp_config: str = ""  # empty = use default
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "name": self.name,
            "prompt": self.prompt,
            "cwd": self.cwd,
            "mcp_config": self.mcp_config,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TopicConfig:
        return cls(
            topic_id=data["topic_id"],
            name=data.get("name", ""),
            prompt=data.get("prompt", DEFAULT_PROMPT),
            cwd=data.get("cwd", ""),
            mcp_config=data.get("mcp_config", ""),
            enabled=data.get("enabled", True),
        )


class TopicManager:
    """Manage forum topic configurations."""

    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._topics: dict[int, TopicConfig] = {}
        self._load()

    def get(self, topic_id: int | None) -> TopicConfig | None:
        """Get config for a topic. Returns None if not configured."""
        if topic_id is None:
            return None
        return self._topics.get(topic_id)

    def get_or_default(self, topic_id: int | None, default_cwd: str = "", default_mcp: str = "") -> TopicConfig:
        """Get config for a topic, or return a default config."""
        if topic_id and topic_id in self._topics:
            return self._topics[topic_id]
        return TopicConfig(
            topic_id=topic_id or 0,
            name="General",
            cwd=default_cwd,
            mcp_config=default_mcp,
        )

    def add(self, config: TopicConfig) -> None:
        """Add or update a topic config."""
        self._topics[config.topic_id] = config
        self._save()
        logger.info("Topic config added: %d — %s", config.topic_id, config.name)

    def remove(self, topic_id: int) -> bool:
        """Remove a topic config."""
        if topic_id in self._topics:
            del self._topics[topic_id]
            self._save()
            return True
        return False

    def list_all(self) -> list[TopicConfig]:
        """List all configured topics."""
        return list(self._topics.values())

    def _save(self) -> None:
        data = [t.to_dict() for t in self._topics.values()]
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for item in data:
                t = TopicConfig.from_dict(item)
                self._topics[t.topic_id] = t
            logger.info("Loaded %d topic configs", len(self._topics))
        except Exception:
            logger.exception("Failed to load topic configs")
