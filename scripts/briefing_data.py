#!/usr/bin/env python3
"""Утренний брифинг d-brain — формирует ГОТОВЫЙ Telegram-HTML детерминированно (без Claude).

Печатает в stdout итоговое сообщение. Календарь/Gmail сейчас отключены — блоки
показываются только при наличии данных.
"""
import asyncio
import os
import sys
from datetime import date

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # для report_fmt

from report_fmt import esc, clean_name, fmt_due, label_of, task_html  # noqa: E402

# Сколько горячих задач показываем в брифинге и сколько строк даём одному проекту.
# Остаток не проглатываем молча — досчитываем в хвосте блока.
HOT_TOTAL = 10
HOT_PER_PROJECT = 3


async def fetch_tasks() -> dict:
    from d_brain.services.notion import NotionClient

    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        return {}
    c = NotionClient(token)
    return {
        "overdue": await c.query_tasks("overdue", limit=20),
        "today": await c.query_tasks("today", limit=30),
        "daily": await c.query_tasks("daily", limit=15),
        "hot": await c.query_tasks("hot", fetch_all=True),
    }


def hot_block(hot: list[dict]) -> list[str]:
    """Горячее без срока, сгруппированное по проектам: крупные блоки сверху."""
    groups: dict[str, list[str]] = {}
    for t in hot:
        groups.setdefault(label_of(t["name"]) or "Без проекта", []).append(t["name"])

    lines = [f"\n🔥 <b>Горячее без срока ({len(hot)}):</b>"]
    shown = 0
    for label in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        # Порядок внутри группы Notion не хранит (сортировка идёт по пустому сроку),
        # поэтому решаем сами: свои дела выше, делегированные Игорю — ниже.
        names = sorted(groups[label], key=lambda n: "(Игорь)" in n)
        if shown >= HOT_TOTAL:
            break
        take = names[: min(HOT_PER_PROJECT, HOT_TOTAL - shown)]
        lines.append(f"<b>{esc(label)}</b> ({len(names)})")
        lines.extend(f"• {esc(clean_name(n))}" for n in take)
        shown += len(take)

    if shown < len(hot):
        lines.append(f"<i>…и еще {len(hot) - shown} — полный список в карте задач</i>")
    return lines


def fetch_streaks() -> str:
    """Серии по ядру ритуалов. Молчим, если трекер ещё не заведён или пуст."""
    try:
        from d_brain.services.habits import HabitStore, streaks_line

        # VAULT_PATH относительный («./vault») — разрешаем от корня проекта,
        # иначе брифинг читал бы пустую историю мимо настоящей.
        vault = os.environ.get("VAULT_PATH") or "vault"
        if not os.path.isabs(vault):
            vault = os.path.join(PROJECT_DIR, vault)
        return streaks_line(HabitStore(os.path.join(vault, "habits.json")))
    except Exception as e:
        print(f"Streaks error: {e}", file=sys.stderr)
        return ""


async def main() -> None:
    today = date.today().strftime("%d.%m.%Y")
    try:
        d = await fetch_tasks()
    except Exception as e:
        print(f"Notion error: {e}", file=sys.stderr)
        d = {}

    overdue = d.get("overdue", [])
    today_tasks = d.get("today", [])
    daily = d.get("daily", [])
    hot = d.get("hot", [])

    P = [f"🌅 <b>Доброе утро! {today}</b>"]

    if overdue:
        P.append(f"\n🔴 <b>Просрочено ({len(overdue)}):</b>")
        for t in overdue:
            P.append(f"• {task_html(t['name'])} <i>— до {fmt_due(t.get('due_date', ''))}</i>")

    if today_tasks:
        P.append(f"\n✅ <b>На сегодня ({len(today_tasks)}):</b>")
        for t in today_tasks:
            P.append(f"• {task_html(t['name'])}")

    if hot:
        P.extend(hot_block(hot))

    if daily:
        P.append("\n🔁 <b>Ежедневно:</b>")
        for t in daily:
            P.append(f"• {esc(clean_name(t['name']))}")

    streaks = fetch_streaks()
    if streaks:
        P.append(f"\n📈 <b>Серии:</b> {esc(streaks)}")

    if not (overdue or today_tasks or hot):
        P.append("\nЗадач на сегодня нет — можно выдохнуть 🎉")

    print("\n".join(P))


if __name__ == "__main__":
    asyncio.run(main())
