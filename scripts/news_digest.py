#!/usr/bin/env python3
"""News digest — fetch channels, deduplicate, rank, post to topics.

Run via systemd timer or manually:
    uv run python scripts/news_digest.py [--topic marketing|dc_energy|ai|personal|all]
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))

from d_brain.services.channel_parser import ChannelPost, fetch_multiple_channels

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MOSCOW_TZ = timezone(timedelta(hours=3))
CONFIG_PATH = PROJECT_DIR / "config" / "news_channels.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def format_posts_for_claude(posts: list[ChannelPost], topic_name: str) -> str:
    """Format posts as text for Claude to rank and summarize."""
    if not posts:
        return ""

    lines = [f"=== ПОСТЫ ИЗ КАНАЛОВ: {topic_name} ({len(posts)} шт) ===\n"]
    for i, p in enumerate(posts, 1):
        lines.append(
            f"--- Пост {i} ---\n"
            f"Канал: {p.channel_name}\n"
            f"Дата: {p.date.strftime('%d.%m %H:%M')}\n"
            f"Просмотры: {p.views}\n"
            f"Ссылка: {p.url}\n"
            f"Текст: {p.text}\n"
        )
    lines.append("=== КОНЕЦ ПОСТОВ ===")
    return "\n".join(lines)


def run_claude_digest(posts_text: str, topic_name: str) -> str:
    """Run Claude to create a ranked digest."""
    today = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")

    prompt = f"""Ты — редактор новостного дайджеста. Создай краткий дайджест из постов телеграм-каналов.

Текущее время: {today} (МСК)
Тема: {topic_name}

{posts_text}

ИНСТРУКЦИЯ:
1. Убери дубликаты (одна и та же новость из разных каналов)
2. Убери рекламу, промо-посты, анонсы курсов/вебинаров
3. Отранжируй по важности и актуальности
4. Выбери топ-15 самых важных/интересных
5. Для каждой новости: краткое описание (1-2 предложения) + ссылка

ФОРМАТ (строго HTML для Telegram):
📰 <b>Дайджест: {topic_name}</b>
<i>{today}</i>

1. <b>Заголовок новости</b>
Краткое описание.
<a href="ссылка">Читать →</a>

2. <b>Заголовок новости</b>
Краткое описание.
<a href="ссылка">Читать →</a>

...

ПРАВИЛА:
- ТОЛЬКО HTML теги: <b>, <i>, <a href="">
- Без markdown
- Максимум 4000 символов
- Нумерованный список
- Каждая новость = заголовок + 1-2 предложения + ссылка"""

    env = os.environ.copy()
    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_DIR),
            env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        logger.error("Claude failed: %s", result.stderr)
    except Exception as e:
        logger.error("Claude error: %s", e)

    return ""


async def fetch_private_channel_posts(
    bot_token: str,
    chat_id: int,
    channel_name: str,
    hours: int = 24,
) -> list[ChannelPost]:
    """Fetch posts from a private channel where bot is admin."""
    from aiogram import Bot

    bot = Bot(token=bot_token)
    posts: list[ChannelPost] = []
    cutoff = datetime.now(MOSCOW_TZ) - timedelta(hours=hours)

    try:
        # Bot API doesn't have getHistory, but we can use getUpdates
        # For private channels, we'll read from forwarded messages
        # Actually, we need to use a different approach
        # For now, skip private channels — they need Telethon
        logger.info("Private channel %s (%d) — skipping (needs Telethon)", channel_name, chat_id)
    except Exception as e:
        logger.warning("Private channel error: %s", e)
    finally:
        await bot.session.close()

    return posts


async def send_digest(bot_token: str, chat_id: int, topic_id: int | None, text: str) -> bool:
    """Send digest to a topic in the group."""
    from aiogram import Bot

    bot = Bot(token=bot_token)
    try:
        kwargs = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if topic_id:
            kwargs["message_thread_id"] = topic_id
        await bot.send_message(**kwargs)
        return True
    except Exception as e:
        logger.error("Failed to send digest: %s", e)
        # Try without HTML
        try:
            kwargs["parse_mode"] = None
            await bot.send_message(**kwargs)
            return True
        except Exception:
            pass
        return False
    finally:
        await bot.session.close()


async def process_topic(
    topic_key: str,
    config: dict,
    bot_token: str,
    hours: int = 24,
) -> None:
    """Process a single topic: fetch, rank, post."""
    topic_config = config["topics"].get(topic_key)
    if not topic_config:
        logger.warning("Topic %s not found in config", topic_key)
        return

    topic_name = topic_config.get("topic_name", topic_key)
    channels = topic_config.get("channels", [])
    group_chat_id = topic_config.get("group_chat_id")
    topic_id = topic_config.get("topic_id")

    if not channels:
        logger.info("No channels configured for %s", topic_key)
        return

    logger.info("Fetching %d channels for %s...", len(channels), topic_name)
    posts = await fetch_multiple_channels(channels, hours=hours, topic=topic_key)
    logger.info("Got %d posts for %s", len(posts), topic_name)

    if not posts:
        logger.info("No new posts for %s", topic_name)
        return

    posts_text = format_posts_for_claude(posts, topic_name)
    logger.info("Running Claude digest for %s...", topic_name)
    digest = run_claude_digest(posts_text, topic_name)

    if not digest:
        logger.error("Claude returned empty digest for %s", topic_name)
        return

    if group_chat_id:
        logger.info("Sending digest to topic %s...", topic_name)
        ok = await send_digest(bot_token, group_chat_id, topic_id, digest)
        logger.info("Digest sent: %s", ok)
    else:
        # Print to stdout if no chat configured
        print(f"\n{'='*60}")
        print(f"DIGEST: {topic_name}")
        print(f"{'='*60}")
        print(digest)


async def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="all", help="Topic to process: marketing|dc_energy|ai|personal|all")
    parser.add_argument("--hours", type=int, default=24, help="Hours to look back")
    parser.add_argument("--dry-run", action="store_true", help="Don't send to Telegram, just print")
    args = parser.parse_args()

    config = load_config()

    # Load bot token
    env_path = PROJECT_DIR / ".env"
    bot_token = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                bot_token = line.split("=", 1)[1]

    topics_to_process = []
    if args.topic == "all":
        topics_to_process = ["marketing", "dc_energy", "ai"]
    else:
        topics_to_process = [args.topic]

    for topic_key in topics_to_process:
        await process_topic(topic_key, config, bot_token, hours=args.hours)


if __name__ == "__main__":
    asyncio.run(main())
