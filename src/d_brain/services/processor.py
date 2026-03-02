"""Claude processing service."""

import logging
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from d_brain.services.session import SessionStore

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 1200  # 20 minutes


class ClaudeProcessor:
    """Service for triggering Claude Code processing."""

    def __init__(self, vault_path: Path, notion_token: str = "") -> None:
        self.vault_path = Path(vault_path)
        self.notion_token = notion_token
        self._mcp_config_path = (self.vault_path.parent / "mcp-config.json").resolve()

    def _load_skill_content(self) -> str:
        """Load dbrain-processor skill content for inclusion in prompt.

        NOTE: @vault/ references don't work in --print mode,
        so we must include skill content directly in the prompt.
        """
        skill_path = self.vault_path / ".claude/skills/dbrain-processor/SKILL.md"
        if skill_path.exists():
            return skill_path.read_text()
        return ""

    def _get_session_context(self, user_id: int) -> str:
        """Get today's session context for Claude."""
        if user_id == 0:
            return ""

        session = SessionStore(self.vault_path)
        today_entries = session.get_today(user_id)
        if not today_entries:
            return ""

        lines = ["=== TODAY'S SESSION ==="]
        for entry in today_entries[-10:]:
            ts = entry.get("ts", "")[11:16]  # HH:MM from ISO
            entry_type = entry.get("type", "unknown")
            text = entry.get("text", "")[:80]
            if text:
                lines.append(f"{ts} [{entry_type}] {text}")
        lines.append("=== END SESSION ===\n")
        return "\n".join(lines)

    def _html_to_markdown(self, html: str) -> str:
        """Convert Telegram HTML to Obsidian Markdown."""
        import re

        text = html
        text = re.sub(r"<b>(.*?)</b>", r"**\1**", text)
        text = re.sub(r"<i>(.*?)</i>", r"*\1*", text)
        text = re.sub(r"<code>(.*?)</code>", r"`\1`", text)
        text = re.sub(r"<s>(.*?)</s>", r"~~\1~~", text)
        text = re.sub(r"</?u>", "", text)
        text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"[\2](\1)", text)
        return text

    def _save_weekly_summary(self, report_html: str, week_date: date) -> Path:
        """Save weekly summary to vault/summaries/YYYY-WXX-summary.md."""
        year, week, _ = week_date.isocalendar()
        filename = f"{year}-W{week:02d}-summary.md"
        summary_path = self.vault_path / "summaries" / filename

        content = self._html_to_markdown(report_html)
        frontmatter = f"""---
date: {week_date.isoformat()}
type: weekly-summary
week: {year}-W{week:02d}
---

"""
        summary_path.write_text(frontmatter + content)
        logger.info("Weekly summary saved to %s", summary_path)
        return summary_path

    def _update_weekly_moc(self, summary_path: Path) -> None:
        """Add link to new summary in MOC-weekly.md."""
        moc_path = self.vault_path / "MOC" / "MOC-weekly.md"
        if moc_path.exists():
            content = moc_path.read_text()
            link = f"- [[summaries/{summary_path.name}|{summary_path.stem}]]"
            if summary_path.stem not in content:
                content = content.replace(
                    "## Previous Weeks\n",
                    f"## Previous Weeks\n\n{link}\n",
                )
                moc_path.write_text(content)
                logger.info("Updated MOC-weekly.md with link to %s", summary_path.stem)

    def _run_claude(self, prompt: str) -> dict[str, Any]:
        """Run Claude CLI with the given prompt and return a result dict.

        All subprocess invocation and error handling is centralised here.
        Callers only need to build the prompt and handle any post-processing.
        """
        env = os.environ.copy()
        env["MCP_TIMEOUT"] = "30000"
        env["MAX_MCP_OUTPUT_TOKENS"] = "50000"
        if self.notion_token:
            env["NOTION_TOKEN"] = self.notion_token

        try:
            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    "--mcp-config",
                    str(self._mcp_config_path),
                    "-p",
                    prompt,
                ],
                cwd=self.vault_path.parent,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                check=False,
                env=env,
            )

            if result.returncode != 0:
                logger.error("Claude failed: %s", result.stderr)
                return {"error": result.stderr or "Ошибка выполнения Claude", "processed_entries": 0}

            return {"report": result.stdout.strip(), "processed_entries": 1}

        except subprocess.TimeoutExpired:
            logger.error("Claude timed out after %ds", DEFAULT_TIMEOUT)
            return {"error": "Превышено время ожидания (20 мин)", "processed_entries": 0}
        except FileNotFoundError:
            logger.error("Claude CLI not found")
            return {"error": "Claude CLI не установлен", "processed_entries": 0}
        except Exception as e:
            logger.exception("Unexpected error during Claude execution")
            return {"error": str(e), "processed_entries": 0}

    def process_daily(self, day: date | None = None) -> dict[str, Any]:
        """Process daily file with Claude."""
        if day is None:
            day = date.today()

        daily_file = self.vault_path / "daily" / f"{day.isoformat()}.md"
        if not daily_file.exists():
            logger.warning("No daily file for %s", day)
            return {"error": f"Нет дневника за {day}", "processed_entries": 0}

        skill_content = self._load_skill_content()
        prompt = f"""Сегодня {day}. Выполни ежедневную обработку.

=== SKILL INSTRUCTIONS ===
{skill_content}
=== END SKILL ===

MCP TOOLS:
- Для задач используй Notion: mcp__notion__API-post-database-query (database_id: "305289eb-342c-80ec-856d-f1c014cdff68")
- НЕ упоминай Todoist — его нет и не будет

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ## , no ```, no tables
- Start directly with 📊 <b>Обработка за {day}</b>
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- If entries already processed, return status report in same HTML format"""

        return self._run_claude(prompt)

    def execute_prompt(self, user_prompt: str, user_id: int = 0) -> dict[str, Any]:
        """Execute arbitrary prompt with Claude."""
        today = date.today()
        session_context = self._get_session_context(user_id)

        prompt = f"""Ты - персональный ассистент d-brain.

CONTEXT:
- Текущая дата: {today}
- Vault path: {self.vault_path}

{session_context}MCP TOOLS:
- Для задач используй Notion: mcp__notion__API-post-database-query (database_id: "305289eb-342c-80ec-856d-f1c014cdff68")
- Для создания задач: mcp__notion__API-post-page
- НЕ упоминай Todoist — его нет и не будет

USER REQUEST:
{user_prompt}

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables, no -
- Start with emoji and <b>header</b>
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Be concise - Telegram has 4096 char limit

EXECUTION:
1. Analyze the request
2. Call MCP tools directly (mcp__notion__*, read/write files)
3. Return HTML status report with results"""

        return self._run_claude(prompt)

    def analyze_emails(self, email_data: str) -> dict[str, Any]:
        """Analyze emails with Claude: extract tasks, create in Notion, return report."""
        today = date.today()

        prompt = f"""Ты — персональный ассистент d-brain. Проанализируй входящую почту.

CONTEXT:
- Текущая дата: {today}

{email_data}

MCP TOOLS:
- Для создания задач: mcp__notion__API-post-page
- database_id задач: "305289eb-342c-80ec-856d-f1c014cdff68"
- НЕ упоминай Todoist

МАППИНГ ПРОЕКТОВ (используй relation при создании задач):
- Контент-завод тексты: 305289eb-342c-8006-b59e-f5cc3156c7d8
- Организации и ассоциации: 305289eb-342c-801d-aa76-fb2c76b439ff
- Hubspot+Skillbox: 305289eb-342c-8022-9f4d-c627b3852e00
- Контент-завод видео: 305289eb-342c-8027-8f66-dcd90a486ea6
- Социальные сети: 305289eb-342c-802a-8e6e-fb2a4ec5d153
- Стратегия: 305289eb-342c-8046-a5f5-da9d87ea9012
- Маркетинговые материалы: 305289eb-342c-807c-91d4-d1c63b5b6a9a
- Zapusk International: 305289eb-342c-8085-920e-f362f112a740
- Мероприятия: 305289eb-342c-8096-ae8f-cbac8371998d
- Встречи и совещания: 305289eb-342c-8098-80f9-c8bab1a00270
- Лидогенерация: 305289eb-342c-80ce-babb-c87b1f0da95d
- СМИ: 305289eb-342c-80ed-b643-fb4d6dd71d82
- Запуск Энергосбыт: 305289eb-342c-80f1-b140-c755496996ce

ИНСТРУКЦИЯ:
1. Прочитай каждое письмо
2. ИГНОРИРУЙ: рассылки, уведомления сервисов (Jira, GitHub, Slack, HubSpot notifications), спам, маркетинговые рассылки
3. Из ВАЖНЫХ писем (от людей, с конкретными запросами/задачами) — создай задачи в Notion через mcp__notion__API-post-page
4. Для каждой задачи задай: Name (title), Status="Not started", Срок выполнения (если упомянут), Проект (relation, если определяется)
5. Верни HTML-отчёт

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown
- Формат:
📧 <b>Анализ почты</b>

📬 Писем: N (из них важных: M)

✅ <b>Созданные задачи:</b>
• Название задачи (от кого)
• Название задачи (от кого)

📋 <b>К сведению:</b>
• Краткое содержание важного письма
(только если не создана задача)

- Allowed tags: <b>, <i>, <code>
- Be concise - Telegram has 4096 char limit"""

        return self._run_claude(prompt)

    def generate_weekly(self) -> dict[str, Any]:
        """Generate weekly digest with Claude."""
        today = date.today()
        prompt = f"""Сегодня {today}. Сгенерируй недельный дайджест.

MCP TOOLS:
- Для задач используй Notion: mcp__notion__API-post-database-query (database_id: "305289eb-342c-80ec-856d-f1c014cdff68")
- НЕ упоминай Todoist — его нет и не будет

WORKFLOW:
1. Собери данные за неделю (daily файлы в vault/daily/, задачи из Notion через MCP)
2. Проанализируй прогресс по целям (goals/3-weekly.md)
3. Определи победы и вызовы
4. Сгенерируй HTML отчёт

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables
- Start with 📅 <b>Недельный дайджест</b>
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Be concise - Telegram has 4096 char limit"""

        result = self._run_claude(prompt)

        if "error" not in result:
            try:
                summary_path = self._save_weekly_summary(result["report"], today)
                self._update_weekly_moc(summary_path)
            except Exception as e:
                logger.warning("Failed to save weekly summary: %s", e)

        return result
