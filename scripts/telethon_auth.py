#!/usr/bin/env python3
"""One-time Telethon authorization script.

Run interactively: uv run python scripts/telethon_auth.py
Enter the code from Telegram when prompted.
"""

import asyncio
import os
import sys

from telethon import TelegramClient

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

async def main():
    env_path = os.path.join(PROJECT_DIR, ".env")
    api_id = ""
    api_hash = ""
    for line in open(env_path):
        if line.startswith("TELEGRAM_API_ID="):
            api_id = line.strip().split("=", 1)[1]
        if line.startswith("TELEGRAM_API_HASH="):
            api_hash = line.strip().split("=", 1)[1]

    if not api_id or not api_hash:
        print("ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH not found in .env")
        sys.exit(1)

    session_path = os.path.join(PROJECT_DIR, "telethon.session")
    client = TelegramClient(session_path, int(api_id), api_hash)

    await client.start(phone="+79175529308")
    me = await client.get_me()
    print(f"Authorized as: {me.first_name} {me.last_name or ''} (@{me.username})")
    print(f"Session saved to: {session_path}")
    await client.disconnect()


asyncio.run(main())
