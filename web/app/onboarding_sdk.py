# ABOUTME: Makes one bounded tool-free Claude request for explicitly reviewed grimoire snippets.
# ABOUTME: Returns structured draft data and actual call measurements without workspace access.
from __future__ import annotations

import time
from tempfile import TemporaryDirectory
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import ResultMessage

from app.onboarding import SECTIONS, STATUSES

DRAFT_SCHEMA = {
    "type": "object", "properties": {"sections": {"type": "array", "items": {
        "type": "object", "properties": {"title": {"type": "string", "enum": list(SECTIONS)},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "kind": {"type": "string", "enum": ["fact", "preference"]},
            "source_id": {"type": "string"}, "quote": {"type": "string"},
            "status": {"type": "string", "enum": [*STATUSES, "unknown"]}},
            "required": ["text", "kind", "source_id", "quote", "status"], "additionalProperties": False}}},
        "required": ["title", "items"], "additionalProperties": False}}},
    "required": ["sections"], "additionalProperties": False,
}


class OnboardingSdk:
    def __init__(self, client_factory: Any = ClaudeSDKClient):
        self.client_factory = client_factory

    async def draft(self, prompt: str) -> tuple[object, dict]:
        started = time.monotonic()
        with TemporaryDirectory(prefix="conjurer-onboarding-") as directory:
            options = ClaudeAgentOptions(cwd=directory, tools=[], allowed_tools=[], setting_sources=[],
                                         skills=[], plugins=[], strict_mcp_config=True, permission_mode="dontAsk",
                                         max_turns=3, max_budget_usd=0.10,
                                         output_format={"type": "json_schema", "schema": DRAFT_SCHEMA})
            result = None
            async with self.client_factory(options=options) as client:
                await client.query(prompt)
                async for message in client.receive_response():
                    if isinstance(message, ResultMessage):
                        result = message
            if result is None or result.is_error:
                raise ValueError("Claude did not complete a grimoire draft. Your sources and saved draft are unchanged.")
            usage = result.usage or {}
            return result.structured_output, {
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                "cost_usd": result.total_cost_usd,
            }
