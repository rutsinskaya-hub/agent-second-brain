#!/usr/bin/env python3
"""One-time script to find channel chat IDs from recent bot updates."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from aiogram import Bot


async def main():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    token = ""
    for line in open(env_path):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.strip().split("=", 1)[1]
            break

    bot = Bot(token=token)

    print("Polling for 30 seconds... Send messages in your channels now!")
    seen = set()
    for _ in range(10):
        updates = await bot.get_updates(timeout=3)
        for u in updates:
            if u.channel_post and u.channel_post.chat.id not in seen:
                p = u.channel_post
                seen.add(p.chat.id)
                print(f"CHANNEL: id={p.chat.id} title={p.chat.title}")
            if u.message and u.message.chat.id not in seen:
                m = u.message
                seen.add(m.chat.id)
                print(f"CHAT: id={m.chat.id} type={m.chat.type} title={m.chat.title or 'private'}")

    await bot.session.close()
    if not seen:
        print("No new messages received. Make sure bot is admin in channels and send a message.")


asyncio.run(main())
