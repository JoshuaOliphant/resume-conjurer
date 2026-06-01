# ABOUTME: Live GenerationPort — the Claude Agent SDK adapter that produces outline + variants.
# ABOUTME: Pure prompt/parse helpers are unit-tested; the thin SDK I/O is exercised by the live test.
"""The agent, sitting behind GenerationPort.

Verified against the SDK live (see web/IMPLEMENTATION_PLAN.md "Spike results"):

- Outline uses a client with ``output_format`` = OUTLINE_SCHEMA and reads
  ``ResultMessage.structured_output``.
- Variants use a SEPARATE persistent client (no output_format) that dispatches the
  plugin's ``conjurer:variant-generator`` subagent and relays its native ``## Unit:``
  block; we extract the variants from that block.
- The persistent variant client is reused across units so the big context prefix stays
  warm in the prompt cache.

All judgment-free logic (prompt building, structured -> Outline, block -> Variants) lives
in module-level pure functions covered by offline tests. The handful of lines that actually
talk to the SDK are marked ``# pragma: no cover`` and are covered by the ``@pytest.mark.live``
integration test, which is the only place real generation can be observed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.domain import Evidence, Outline, OutlineUnit, UnitKind, Variant
from app.metrics import CallMetrics
from app.schemas import OUTLINE_SCHEMA

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PLUGIN_DIR = REPO_ROOT / "plugins" / "conjurer"
DEFAULT_MODEL = "claude-sonnet-4-6"

# The only tools the variant agent may use: read/search and subagent dispatch. This is a
# deny-by-default allowlist, not a denylist — anything not named here (unknown built-ins,
# any mcp__* tool, future tools) is denied. The variant client reads the JD and evidence,
# which may be attacker-influenced (a pasted job post), so a prompt injection must never be
# able to reach code execution or exfiltration. The variant client cannot use a `tools`
# allowlist (that breaks plugin subagent dispatch), so this allowlist is enforced two ways:
# via `allowed_tools` (auto-approval) AND via the can_use_tool callback below, with
# permission_mode left off bypass so the callback is actually consulted.
ALLOWED_VARIANT_TOOLS = frozenset({"Read", "Glob", "Grep", "Agent", "Task"})

# A relayed variant block: "### Variant 1: <citation>" then body, ending before the
# next header / an "*Axis: ...*" line / a "- [ ] Pick" line.
# Inline whitespace around the citation is [ \t] (not \s) so an empty citation does not
# let the matcher swallow the newlines into the next line; the body is DOTALL.
_VARIANT_RE = re.compile(
    r"^###[ \t]+Variant[ \t]+(\d+)[ \t]*:[ \t]*(?P<citation>.*?)[ \t]*$\n(?P<body>.*?)"
    r"(?=^###[ \t]+Variant[ \t]+\d+[ \t]*:|^\*Axis:|^-[ \t]*\[[ xX]\][ \t]*Pick|\Z)",
    re.MULTILINE | re.DOTALL,
)


# --- Pure helpers (offline-tested) -----------------------------------------


def build_outline_prompt(slug: str) -> str:
    """Prompt for the discrete outline step, grounded in the workspace files for slug."""
    return (
        "Read these files in the current working directory and design a tailored application "
        "outline:\n"
        "- grimoire.md (voice and taste)\n"
        "- master-resume.md (the evidence pool)\n"
        f"- applications/{slug}/jd.txt (the job description)\n"
        f"- applications/{slug}/evidence.md (extra evidence)\n\n"
        "Choose exactly ONE strategic frame: scale, friction, conviction, or multiplier. Then "
        "design the unit skeleton, in document order: the cover-letter paragraphs and the resume "
        "bullets worth tailoring. Resume unit_ids encode the role: "
        "resume.<company>.<subrole?>.bullet_<n>; cover-letter unit_ids start with cover_letter. "
        "Do only the outline. Do not generate variants, initialize anything, or write files."
    )


def build_variant_prompt(unit: OutlineUnit, n: int = 4) -> str:
    """Prompt that dispatches the conjurer:variant-generator subagent for one unit."""
    return (
        f"Use the conjurer:variant-generator subagent to generate {n} grounded variants for this "
        "single unit, citing evidence from master-resume.md (cite as 'master-resume.md L<line>'). "
        f"Read grimoire.md and master-resume.md for grounding.\nUnit: {unit.unit_id} - "
        f"{unit.description}\nReturn the variant-generator's '## Unit:' block verbatim as your "
        "final message."
    )


def outline_from_structured(data: dict[str, Any]) -> Outline:
    """Map a validated outline.json-shaped dict into a domain Outline."""

    def units(items: list[dict[str, Any]], kind: UnitKind) -> tuple[OutlineUnit, ...]:
        return tuple(
            OutlineUnit(unit_id=it["unit_id"], kind=kind, description=it["description"])
            for it in items
        )

    return Outline(
        strategic_frame=data["strategic_frame"],
        frame_rationale=data["frame_rationale"],
        company=data["company"],
        role_title=data["role_title"],
        cover_letter_units=units(data["cover_letter_units"], "cover_paragraph"),
        resume_units=units(data["resume_units"], "resume_bullet"),
    )


def variants_from_block(text: str, unit: OutlineUnit) -> list[Variant]:
    """Parse a relayed variant-generator block into domain Variants for one unit.

    Each variant carries its citation as a lightweight Evidence(id=citation); the
    workspace repository resolves citations to real master-resume lines on load, so the
    UI's trace renders the actual cited text.
    """
    variants: list[Variant] = []
    for match in _VARIANT_RE.finditer(text):
        n = int(match.group(1))
        citation = match.group("citation").strip() or "master-resume.md"
        body = match.group("body").strip()
        if not body:
            continue
        variants.append(
            Variant(
                id=f"{unit.unit_id}#{n}",
                text=body,
                evidence_items=(Evidence(id=citation, text=citation, source=citation),),
            )
        )
    return variants


async def guard_variant_tool(tool_name: str, input_data: dict[str, Any], context: Any) -> Any:
    """can_use_tool guard for the variant client: deny by default, allow only the allowlist.

    Consulted for tools not auto-approved via ``allowed_tools``. Only the read/search and
    subagent-dispatch tools in :data:`ALLOWED_VARIANT_TOOLS` are permitted; everything else —
    code execution, file writes, network, unknown built-ins, any ``mcp__*`` tool — is denied.
    This is the defense against a prompt injection in the (user-pasted, possibly hostile) job
    description or evidence.
    """
    from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

    if tool_name in ALLOWED_VARIANT_TOOLS:
        return PermissionResultAllow()
    return PermissionResultDeny(
        message=f"{tool_name} is not permitted during variant generation (read-only)."
    )


# --- The adapter (thin SDK I/O; live-tested) -------------------------------


class SdkGenerationPort:
    """GenerationPort backed by the Claude Agent SDK and the conjurer plugin."""

    def __init__(
        self,
        workspace: Path,
        plugin_dir: Path = DEFAULT_PLUGIN_DIR,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.workspace = Path(workspace)
        self.plugin_dir = Path(plugin_dir)
        self.model = model
        self._variant_client: Any = None
        # Metrics of the most recent call, for observability and the live cache assertion.
        self.last_call: CallMetrics | None = None

    def _base_options(self) -> dict[str, Any]:  # pragma: no cover - SDK wiring, live-tested
        # No permission_mode here; each client sets its own. The outline client can safely
        # bypass (its `tools` allowlist removes mutating tools entirely); the variant client
        # must NOT bypass, so its can_use_tool guard is consulted.
        return dict(
            cwd=str(self.workspace),
            plugins=[{"type": "local", "path": str(self.plugin_dir)}],
            setting_sources=[],
            model=self.model,
        )

    async def outline(self, slug: str) -> Outline:  # pragma: no cover - live-tested
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        from claude_agent_sdk.types import ResultMessage

        options = ClaudeAgentOptions(
            # `tools` restricts the AVAILABLE toolset (least privilege); `allowed_tools`
            # only auto-approves. The outline step needs no subagent, so restricting `tools`
            # to read-only here removes mutating tools entirely, making bypass safe.
            tools=["Read", "Glob", "Grep"],
            allowed_tools=["Read", "Glob", "Grep"],
            permission_mode="bypassPermissions",
            output_format={"type": "json_schema", "schema": OUTLINE_SCHEMA},
            **self._base_options(),
        )
        structured: Any = None
        async with ClaudeSDKClient(options=options) as client:
            await client.query(build_outline_prompt(slug))
            async for msg in client.receive_response():
                if isinstance(msg, ResultMessage):
                    structured = msg.structured_output
                    self.last_call = CallMetrics.from_result(msg)
        if not isinstance(structured, dict):
            raise RuntimeError("Outline generation returned no structured output")
        return outline_from_structured(structured)

    async def _variant_text(self, prompt: str) -> str:  # pragma: no cover - live-tested
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock

        if self._variant_client is None:
            # The variant client dispatches the plugin subagent, which an explicit `tools`
            # allowlist breaks (verified live: variants come back empty). So we keep the
            # default toolset but DROP bypassPermissions and supply a can_use_tool guard,
            # so a prompt injection in the JD/evidence cannot reach Bash/Write/Edit/network.
            # allowed_tools auto-approves the safe set; guard_variant_tool denies everything
            # else by default. NB (lead to live-verify): subagent dispatch must still work
            # under this allowlist — `Agent`/`Task` are allowed so the variant-generator runs.
            options = ClaudeAgentOptions(
                allowed_tools=["Read", "Glob", "Grep", "Agent"],
                can_use_tool=guard_variant_tool,
                **self._base_options(),
            )
            self._variant_client = ClaudeSDKClient(options=options)
            await self._variant_client.connect()
        await self._variant_client.query(prompt)
        parts: list[str] = []
        async for msg in self._variant_client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                self.last_call = CallMetrics.from_result(msg)
        return "\n".join(parts)

    async def variants(  # pragma: no cover - live-tested
        self, slug: str, unit: OutlineUnit, n: int = 4
    ) -> list[Variant]:
        text = await self._variant_text(build_variant_prompt(unit, n))
        return variants_from_block(text, unit)

    async def aclose(self) -> None:  # pragma: no cover - live-tested
        if self._variant_client is not None:
            await self._variant_client.disconnect()
            self._variant_client = None
