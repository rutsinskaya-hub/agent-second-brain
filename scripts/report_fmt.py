"""Хелперы для детерминированной сборки отчётов d-brain (без Claude/sed)."""
import re

_PREFIX = re.compile(r"^[^\[]*\[[^\]]*\]\s*")
_TRAIL_DATE = re.compile(r"\s*\(\d{1,2}\.\d{2}(?:\.\d{4})?\)\s*$")
_DUE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_LABEL = re.compile(r"^[^\[]*\[([^\]]*)\]")


def esc(s: str) -> str:
    """HTML-escape для Telegram parse_mode=HTML — чтобы & < > в тексте задач не ломали парсинг."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clean_name(name: str) -> str:
    """Убирает префикс '<эмодзи> [проект] ' и хвостовую '(дата)'; схлопывает пробелы."""
    n = _PREFIX.sub("", name or "")
    n = _TRAIL_DATE.sub("", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n or (name or "").strip()


def label_of(name: str) -> str:
    """Проект из '<эмодзи> [проект] текст'. Для 'АНКО/Школа КОНТЕКСТ' → 'Школа КОНТЕКСТ' (последний сегмент)."""
    m = _LABEL.match(name or "")
    if not m:
        return ""
    lbl = m.group(1).strip()
    return lbl.split("/")[-1].strip()


def task_html(name: str) -> str:
    """HTML-строка задачи для отчёта: '<b>[Проект]</b> текст' (или просто текст, если проекта нет)."""
    lbl = label_of(name)
    body = esc(clean_name(name))
    return f"<b>[{esc(lbl)}]</b> {body}" if lbl else body


def fmt_due(iso: str) -> str:
    """'2026-06-08' -> '08.06'."""
    m = _DUE.match(iso or "")
    return f"{m.group(3)}.{m.group(2)}" if m else (iso or "")
