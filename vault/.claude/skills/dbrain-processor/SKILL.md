---
name: second-brain-processor
description: Personal assistant for processing daily voice/text entries from Telegram. Classifies content, creates Notion tasks, saves thoughts to Obsidian with wiki-links, generates an HTML report. Triggers on /process.
---

# Second Brain Processor

Process daily entries → tasks (Notion) + thoughts (Obsidian) + HTML report (Telegram).

## CRITICAL: Output Format

**ALWAYS return RAW HTML. No markdown. Ever.** The final output goes straight to
Telegram with `parse_mode=HTML`.

Rules:
1. ALWAYS return an HTML report — even if entries were already processed
2. ALWAYS use the template below — no free-form text
3. NEVER use markdown (**, ##, ```, -)
4. NEVER explain what you did in plain text — put it in the HTML report

## Task backend: Notion (NOT Todoist)

Todoist has been removed. Tasks live ONLY in Notion. Never mention Todoist.

Tasks database_id: `305289eb-342c-80ec-856d-f1c014cdff68`

MCP tools:
- `mcp__notion__API-post-database-query` — find tasks (check duplicates, workload)
- `mcp__notion__API-post-page` — create a task
- `mcp__notion__API-patch-page` — update a task (status, deadline)

Task properties:
- `Задача` (title)
- `Status` (status): "Not started" / "In progress" / "Done"
- `Срок выполнения` (date) — set this directly via the tool, NEVER tell the user
  to update the deadline manually
- `Проект` (relation, optional)

### Tool usage policy

**СНАЧАЛА ВЫЗОВИ TOOL. ПОТОМ ДУМАЙ.** У тебя ЕСТЬ доступ к Notion MCP.

ЗАПРЕЩЕНО:
- ❌ Писать "MCP недоступен"
- ❌ Предлагать "обнови/добавь вручную"
- ❌ Просить вручную проставить срок в Notion
- ❌ Делать HTTP-запросы к API напрямую или через subprocess

ОБЯЗАТЕЛЬНО:
- ✅ Вызывать Notion MCP напрямую (создание, поиск, обновление, срок)
- ✅ При ошибке — подождать и вызвать снова, до 3 раз
- ✅ Показать ТОЧНУЮ ошибку tool, если 3 попытки не прошли

## Processing Flow

1. Read daily — `daily/YYYY-MM-DD.md`
2. Classify each entry — but FIRST apply the skip rule below; only raw entries proceed
3. Tasks → create/update in Notion (status, срок, проект — всё через tool)
4. Thoughts → save to `thoughts/` with [[wiki-links]]
5. Log actions back to `daily/YYYY-MM-DD.md`
6. Generate the HTML report

### CRITICAL: Skip already-handled entries (NO DUPLICATES)

Each daily entry header carries a type tag in brackets. The bot ACTIONS many
intents instantly at capture time (the fast path) and logs them with a sub-tag.
Re-creating those here makes DUPLICATE tasks — this is the #1 bug to avoid.

SKIP entirely — already done, do NOT create or update anything for:
- `[voice][task]`, `[text][task]` — task already created in Notion
- `[voice][complete]`, `[text][complete]` — task already marked Done
- `[voice][deadline]`, `[text][deadline]` — task deadline already moved
- `[voice][reminder]`, `[text][reminder]` — reminder already set
- `[voice][query]`, `[text][query]` — was a read, nothing to create
- any `[*][calendar]`, `[*][calendar-create]`, `[*][email]`, `[*][email-manage]`, `[*][action]`

PROCESS (classify → task or thought) ONLY raw, unrouted entries:
- `[voice]`, `[text]`, `[photo]`, `[note]`, `[forward from: ...]`

Before creating ANY task, also query Notion (`API-post-database-query`) for a task
with a similar title — match loosely, a short spoken phrase vs. a longer stored
title still counts. If one exists, UPDATE it instead of creating a duplicate.

## Classification

- task → Notion (actionable: "позвонить", "оплатить", "подготовить", дедлайны)
- idea / reflection / project / learning → `thoughts/` (see references/classification.md)

## Thought Categories

💡 idea → thoughts/ideas/
🪞 reflection → thoughts/reflections/
🎯 project → thoughts/projects/
📚 learning → thoughts/learnings/

## Logging to daily/ (Step 5)

After any vault change, append to `daily/YYYY-MM-DD.md`:

## HH:MM [text]
{what was done}

**Created/Updated:**
- {task or [[note]]} — description

## HTML Report Template

Output RAW HTML (no markdown, no code blocks):

📊 <b>Обработка за {DATE}</b>

<b>📓 Сохранено мыслей:</b> {N}
• {emoji} {title} → {category}/

<b>✅ Создано задач:</b> {M}
• {task} <i>({срок, если есть})</i>

<b>🔄 Обновлено задач:</b> {K}
• {task} <i>({что изменилось — срок/статус})</i>

<b>📅 Задачи на ближайшие дни:</b>
• {task} — {дата}

<b>⚠️ Требует внимания:</b>
• {просроченные / на сегодня}

<b>🔗 Новые связи:</b>
• [[Note A]] ↔ [[Note B]]

---
<i>Обработано за {duration}</i>

## If Already Processed

If all entries have a `<!-- ✓ processed -->` marker, return a status report in the
same HTML format:

📊 <b>Статус за {DATE}</b>

<b>📅 Задачи:</b>
• Просроченных: {n}
• На сегодня: {n}

<b>⚠️ Требует внимания:</b>
• {детали}

---
<i>Записи уже обработаны ранее</i>

## Allowed HTML Tags

<b> bold · <i> italic · <code> code/paths · <s> strikethrough · <u> underline ·
<a href="url">text</a> links

## FORBIDDEN in Output

NO markdown (**, ##, -, *, backticks) · NO code blocks · NO tables ·
NO unsupported tags (div, span, br, p, table). Max 4096 characters.

## References

- references/about.md — user profile, decision filters
- references/classification.md — entry classification rules
- references/links.md — wiki-links building
