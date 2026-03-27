"""Streaming Claude processor — shows tool calls in real-time.

Runs `claude --print --output-format stream-json --verbose` and
yields events as they arrive, so the bot can show progress.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 1200  # 20 minutes


@dataclass
class StreamEvent:
    """A parsed event from Claude stream-json output."""
    kind: str  # "text", "tool_call", "tool_result", "done", "error"
    text: str = ""
    tool_name: str = ""
    tool_input: str = ""
    cost_usd: float = 0.0
    duration_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _format_tool_call(name: str, input_data: dict[str, Any]) -> str:
    """Format a tool call for Telegram display."""
    icons = {
        "Bash": "⚙️",
        "Read": "📖",
        "Write": "✏️",
        "Edit": "✏️",
        "Glob": "🔍",
        "Grep": "🔍",
        "Git": "📦",
        "WebFetch": "🌐",
        "WebSearch": "🌐",
        "TodoWrite": "📝",
    }
    icon = icons.get(name, "🔧")

    if name == "Bash":
        cmd = input_data.get("command", "")
        desc = input_data.get("description", "")
        display = desc if desc else (cmd[:80] + "..." if len(cmd) > 80 else cmd)
        return f"{icon} <b>{name}:</b> <code>{display}</code>"
    elif name in ("Read", "Write", "Edit"):
        path = input_data.get("file_path", "")
        short = Path(path).name if path else ""
        return f"{icon} <b>{name}:</b> {short}"
    elif name in ("Glob", "Grep"):
        pattern = input_data.get("pattern", "")
        return f"{icon} <b>{name}:</b> <code>{pattern}</code>"
    else:
        # Generic
        summary = str(input_data)[:60]
        return f"{icon} <b>{name}:</b> {summary}"


async def stream_claude(
    prompt: str,
    cwd: str | Path,
    mcp_config: str | Path | None = None,
    notion_token: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> AsyncIterator[StreamEvent]:
    """Run Claude CLI with streaming and yield events.

    Usage:
        async for event in stream_claude("do something", "/path"):
            if event.kind == "tool_call":
                await msg.answer(f"🔧 {event.tool_name}: {event.tool_input}")
            elif event.kind == "text":
                # accumulate text
            elif event.kind == "done":
                # send final result
    """
    cmd = [
        "claude",
        "--print",
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]
    if mcp_config:
        cmd.extend(["--mcp-config", str(mcp_config)])
    cmd.extend(["-p", prompt])

    env = os.environ.copy()
    env["MCP_TIMEOUT"] = "30000"
    env["MAX_MCP_OUTPUT_TOKENS"] = "50000"
    if notion_token:
        env["NOTION_TOKEN"] = notion_token

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
        )
    except FileNotFoundError:
        yield StreamEvent(kind="error", text="Claude CLI не установлен")
        return

    accumulated_text = ""

    try:
        async def read_with_timeout() -> bytes | None:
            assert proc.stdout is not None
            try:
                return await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            except asyncio.TimeoutError:
                return None

        while True:
            line_bytes = await read_with_timeout()
            if line_bytes is None:
                proc.kill()
                yield StreamEvent(kind="error", text="Превышено время ожидания")
                return
            if not line_bytes:
                break

            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = data.get("type", "")

            if event_type == "assistant":
                msg = data.get("message", {})
                content = msg.get("content", [])
                for block in content:
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text.strip():
                            accumulated_text += text
                            yield StreamEvent(kind="text", text=text)

                    elif block.get("type") == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_input = block.get("input", {})
                        formatted = _format_tool_call(tool_name, tool_input)
                        yield StreamEvent(
                            kind="tool_call",
                            tool_name=tool_name,
                            tool_input=formatted,
                            extra=tool_input,
                        )

            elif event_type == "result":
                final_text = data.get("result", accumulated_text)
                yield StreamEvent(
                    kind="done",
                    text=final_text,
                    cost_usd=data.get("total_cost_usd", 0),
                    duration_ms=data.get("duration_ms", 0),
                )
                return

    except Exception as e:
        logger.exception("Stream processing error")
        yield StreamEvent(kind="error", text=str(e))
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
