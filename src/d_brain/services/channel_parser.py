"""Telegram channel parser via Telethon.

Reads channels using authorized user session.
Fetches posts from the last N hours, returns structured data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MOSCOW_TZ = timezone(timedelta(hours=3))
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent
ENTITY_CACHE_PATH = PROJECT_DIR / "config" / "entity_cache.json"


def _load_entity_cache() -> dict[str, int]:
    if ENTITY_CACHE_PATH.exists():
        try:
            return json.loads(ENTITY_CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_entity_cache(cache: dict[str, int]) -> None:
    ENTITY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENTITY_CACHE_PATH.write_text(json.dumps(cache, indent=2))


@dataclass
class ChannelPost:
    """A single post from a Telegram channel."""
    channel: str
    channel_name: str
    text: str
    date: datetime
    url: str
    views: int = 0
    topic: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "channel_name": self.channel_name,
            "text": self.text,
            "date": self.date.isoformat(),
            "url": self.url,
            "views": self.views,
            "topic": self.topic,
        }


def _get_client():
    """Create Telethon client with saved session."""
    from telethon import TelegramClient

    api_id = os.environ.get("TELEGRAM_API_ID", "37810955")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "e70b928b17a0681e8e622daecd000b77")
    session_path = str(PROJECT_DIR / "telethon")

    return TelegramClient(session_path, int(api_id), api_hash)


async def fetch_channel_posts(
    username: str,
    channel_name: str = "",
    hours: int = 24,
    topic: str = "",
    client=None,
) -> list[ChannelPost]:
    """Fetch recent posts from a Telegram channel via Telethon."""
    own_client = client is None
    if own_client:
        client = _get_client()
        await client.connect()

    posts: list[ChannelPost] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    try:
        # Use cached entity ID to avoid ResolveUsername flood bans
        cache = _load_entity_cache()
        if username in cache:
            entity = await client.get_entity(cache[username])
        else:
            entity = await client.get_entity(username)
            cache[username] = entity.id
            _save_entity_cache(cache)
            await asyncio.sleep(1)  # Rate limit on new resolves

        messages = await client.get_messages(entity, limit=30)

        for msg in messages:
            if msg.date < cutoff:
                continue
            if not msg.text or len(msg.text.strip()) < 15:
                continue

            dt_moscow = msg.date.astimezone(MOSCOW_TZ)
            post_url = f"https://t.me/{username}/{msg.id}"

            posts.append(ChannelPost(
                channel=username,
                channel_name=channel_name or username,
                text=msg.text[:500],
                date=dt_moscow,
                url=post_url,
                views=msg.views or 0,
                topic=topic,
            ))
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", username, e)
    finally:
        if own_client:
            await client.disconnect()

    return posts


async def fetch_multiple_channels(
    channels: list[dict[str, str]],
    hours: int = 24,
    topic: str = "",
) -> list[ChannelPost]:
    """Fetch posts from multiple channels using a shared Telethon client."""
    client = _get_client()
    await client.connect()

    all_posts: list[ChannelPost] = []

    for ch in channels:
        username = ch["username"].lstrip("@")
        name = ch.get("name", username)
        try:
            posts = await fetch_channel_posts(username, name, hours, topic, client=client)
            all_posts.extend(posts)
            logger.info("Fetched %d posts from %s", len(posts), username)
        except Exception as e:
            logger.warning("Error fetching %s: %s", username, e)

    await client.disconnect()

    all_posts.sort(key=lambda p: p.date, reverse=True)
    return all_posts


async def fetch_private_channel(
    chat_id: int,
    channel_name: str = "",
    hours: int = 24,
    client=None,
) -> list[ChannelPost]:
    """Fetch posts from a private channel by chat_id."""
    own_client = client is None
    if own_client:
        client = _get_client()
        await client.connect()

    posts: list[ChannelPost] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    try:
        entity = await client.get_entity(chat_id)
        messages = await client.get_messages(entity, limit=30)

        for msg in messages:
            if msg.date < cutoff:
                continue
            text = msg.text or ""
            # For forwarded messages, include forward info
            if msg.forward and not text:
                text = "[Forwarded]"
            if not text or len(text.strip()) < 10:
                continue

            dt_moscow = msg.date.astimezone(MOSCOW_TZ)

            posts.append(ChannelPost(
                channel=str(chat_id),
                channel_name=channel_name or str(chat_id),
                text=text[:500],
                date=dt_moscow,
                url="",
                views=msg.views or 0,
            ))
    except Exception as e:
        logger.warning("Failed to fetch private channel %s: %s", chat_id, e)
    finally:
        if own_client:
            await client.disconnect()

    return posts
