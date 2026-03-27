"""Telegram channel parser via public t.me/s/ pages.

Scrapes public preview pages — no auth, no risk of ban.
Fetches posts from the last N hours, returns structured data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MOSCOW_TZ = timezone(timedelta(hours=3))


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


async def fetch_channel_posts(
    username: str,
    channel_name: str = "",
    hours: int = 24,
    topic: str = "",
) -> list[ChannelPost]:
    """Fetch recent posts from a public Telegram channel.

    Uses t.me/s/username — the public web preview.
    """
    url = f"https://t.me/s/{username}"
    posts: list[ChannelPost] = []
    cutoff = datetime.now(MOSCOW_TZ) - timedelta(hours=hours)

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            if resp.status_code != 200:
                logger.warning("Channel %s returned %d", username, resp.status_code)
                return []
            html = resp.text
    except Exception:
        logger.warning("Failed to fetch channel %s", username)
        return []

    # Parse posts from HTML
    # Each post is in <div class="tgme_widget_message_wrap">
    post_blocks = re.findall(
        r'<div class="tgme_widget_message_wrap.*?">(.*?)</div>\s*</div>\s*</div>',
        html,
        re.DOTALL,
    )

    if not post_blocks:
        # Try alternative pattern
        post_blocks = re.findall(
            r'data-post="([^"]+)".*?'
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>.*?'
            r'<time[^>]*datetime="([^"]+)"',
            html,
            re.DOTALL,
        )
        for post_id, text_html, date_str in post_blocks:
            try:
                dt = datetime.fromisoformat(date_str.replace("+00:00", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt_moscow = dt.astimezone(MOSCOW_TZ)
            except (ValueError, TypeError):
                continue

            if dt_moscow < cutoff:
                continue

            text = _clean_html(text_html)
            if not text or len(text) < 10:
                continue

            post_url = f"https://t.me/{post_id}"
            posts.append(ChannelPost(
                channel=username,
                channel_name=channel_name or username,
                text=text[:500],
                date=dt_moscow,
                url=post_url,
                topic=topic,
            ))
        return posts

    # Fallback: extract all data-post and text blocks separately
    data_posts = re.findall(r'data-post="([^"]+)"', html)
    texts = re.findall(
        r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
        html,
        re.DOTALL,
    )
    dates = re.findall(r'<time[^>]*datetime="([^"]+)"', html)
    views_raw = re.findall(
        r'<span class="tgme_widget_message_views">([^<]+)</span>',
        html,
    )

    for i in range(min(len(data_posts), len(texts), len(dates))):
        try:
            dt = datetime.fromisoformat(dates[i].replace("+00:00", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_moscow = dt.astimezone(MOSCOW_TZ)
        except (ValueError, TypeError):
            continue

        if dt_moscow < cutoff:
            continue

        text = _clean_html(texts[i])
        if not text or len(text) < 10:
            continue

        views = _parse_views(views_raw[i]) if i < len(views_raw) else 0
        post_url = f"https://t.me/{data_posts[i]}"

        posts.append(ChannelPost(
            channel=username,
            channel_name=channel_name or username,
            text=text[:500],
            date=dt_moscow,
            url=post_url,
            views=views,
            topic=topic,
        ))

    return posts


async def fetch_multiple_channels(
    channels: list[dict[str, str]],
    hours: int = 24,
    topic: str = "",
) -> list[ChannelPost]:
    """Fetch posts from multiple channels.

    channels: list of {"username": "@name", "name": "Display Name"}
    """
    import asyncio

    tasks = []
    for ch in channels:
        username = ch["username"].lstrip("@")
        name = ch.get("name", username)
        tasks.append(fetch_channel_posts(username, name, hours, topic))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_posts: list[ChannelPost] = []
    for r in results:
        if isinstance(r, list):
            all_posts.extend(r)
        elif isinstance(r, Exception):
            logger.warning("Channel fetch error: %s", r)

    all_posts.sort(key=lambda p: p.date, reverse=True)
    return all_posts


def _clean_html(html: str) -> str:
    """Strip HTML tags and clean up text."""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_views(raw: str) -> int:
    """Parse view count like '1.2K' or '15'."""
    raw = raw.strip()
    if not raw:
        return 0
    multiplier = 1
    if raw.endswith("K"):
        multiplier = 1000
        raw = raw[:-1]
    elif raw.endswith("M"):
        multiplier = 1000000
        raw = raw[:-1]
    try:
        return int(float(raw) * multiplier)
    except ValueError:
        return 0
