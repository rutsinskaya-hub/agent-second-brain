#!/usr/bin/env python3
"""Утренняя самопроверка d-brain. Алертит в Telegram ТОЛЬКО при проблемах.

Проверяет: бот жив · Notion доступен · число задач адекватно · утренний брифинг отработал сегодня.
"""
import json
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import date

DB = "305289eb-342c-80ec-856d-f1c014cdff68"
NOTION = os.environ.get("NOTION_TOKEN", "")
TG = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("ALLOWED_USER_IDS", "").strip("[]").split(",")[0].strip()

problems = []

# 1) бот жив
try:
    r = subprocess.run(["systemctl", "is-active", "d-brain-bot"], capture_output=True, text=True)
    state = r.stdout.strip()
    if state != "active":
        problems.append(f"бот d-brain-bot не активен (статус: {state or 'unknown'})")
except Exception as e:
    problems.append(f"не смог проверить бота: {e}")

# 2) Notion доступен + число задач адекватно
try:
    H = {"Authorization": f"Bearer {NOTION}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    total, cur, pages = 0, None, 0
    while True:
        body = {"page_size": 100, "filter": {"property": "Status", "status": {"does_not_equal": "Done"}}}
        if cur:
            body["start_cursor"] = cur
        req = urllib.request.Request(f"https://api.notion.com/v1/databases/{DB}/query",
                                     data=json.dumps(body).encode(), headers=H)
        d = json.loads(urllib.request.urlopen(req, timeout=15).read())
        total += len(d.get("results", []))
        pages += 1
        if d.get("has_more") and pages < 6:
            cur = d.get("next_cursor")
        else:
            break
    if total == 0:
        problems.append("в Notion 0 активных задач — возможно, синк всё снёс")
    elif total > 250:
        problems.append(f"в Notion {total} активных задач — подозрительно много (дубли?)")
except Exception as e:
    problems.append(f"Notion недоступен: {e}")

# 3) утренний брифинг отработал сегодня
try:
    r = subprocess.run(["systemctl", "show", "d-brain-briefing.service",
                        "-p", "ExecMainStatus", "-p", "ExecMainStartTimestamp"],
                       capture_output=True, text=True)
    info = dict(line.split("=", 1) for line in r.stdout.strip().splitlines() if "=" in line)
    ts = info.get("ExecMainStartTimestamp", "")  # oneshot: ActiveEnterTimestamp пуст, берём старт ExecMain
    today_str = date.today().strftime("%Y-%m-%d")
    if today_str not in ts:
        problems.append("утренний брифинг сегодня не запускался (таймер?)")
    elif info.get("ExecMainStatus", "0") not in ("0", ""):
        problems.append(f"утренний брифинг упал (код {info.get('ExecMainStatus')})")
except Exception as e:
    problems.append(f"не смог проверить брифинг: {e}")

# алерт только при проблемах
if problems:
    text = "⚠️ Проверка d-brain нашла проблемы:\n" + "\n".join(f"• {p}" for p in problems)
    if TG and CHAT:
        data = urllib.parse.urlencode({"chat_id": CHAT, "text": text}).encode()
        try:
            urllib.request.urlopen(
                urllib.request.Request(f"https://api.telegram.org/bot{TG}/sendMessage", data=data), timeout=10)
        except Exception as e:
            print(f"алерт не отправлен: {e}")
    print("ALERTED:\n" + text)
else:
    print("health OK — проблем нет")
