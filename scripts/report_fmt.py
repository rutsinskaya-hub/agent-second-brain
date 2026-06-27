"""Хелперы для детерминированной сборки отчётов d-brain (без Claude/sed)."""
import re

_PREFIX = re.compile(r"^[^\[]*\[[^\]]*\]\s*")
_TRAIL_DATE = re.compile(r"\s*\(\d{1,2}\.\d{2}(?:\.\d{4})?\)\s*$")
_DUE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def esc(s: str) -> str:
    """HTML-escape для Telegram parse_mode=HTML — чтобы & < > в тексте задач не ломали парсинг."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clean_name(name: str) -> str:
    """Убирает префикс '<эмодзи> [проект] ' и хвостовую '(дата)'; схлопывает пробелы."""
    n = _PREFIX.sub("", name or "")
    n = _TRAIL_DATE.sub("", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n or (name or "").strip()


def fmt_due(iso: str) -> str:
    """'2026-06-08' -> '08.06'."""
    m = _DUE.match(iso or "")
    return f"{m.group(3)}.{m.group(2)}" if m else (iso or "")
