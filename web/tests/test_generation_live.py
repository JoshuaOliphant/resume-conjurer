# ABOUTME: Live integration test for the SDK GenerationPort against the fixture workspace.
# ABOUTME: Marked `live`; deselected by default. Run with: uv run pytest -m live
"""Real-API verification of SdkGenerationPort.

Skipped unless authentication is available (an ANTHROPIC_API_KEY in env/.env, or an
authenticated `claude` CLI — the SDK falls back to it). Run explicitly:

    cd web && uv run pytest -m live

Proves: the outline step returns a schema-valid Outline; the variant step dispatches the
plugin subagent and yields grounded variants with citations; and the persistent variant
client hits the prompt cache on the second unit (cache_read_input_tokens > 0).
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest

from app.adapters.generation_sdk import SdkGenerationPort
from app.domain import FRAMES, Outline

HERE = Path(__file__).parent
FIXTURE_WORKSPACE = HERE / "fixtures" / "workspace"
SLUG = "globex-staff-platform"

pytestmark = pytest.mark.live


def _load_dotenv() -> None:
    env = HERE.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _auth_available() -> bool:
    _load_dotenv()
    return bool(os.environ.get("ANTHROPIC_API_KEY")) or shutil.which("claude") is not None


@pytest.mark.skipif(not _auth_available(), reason="no ANTHROPIC_API_KEY and no claude CLI")
def test_live_outline_and_variants_with_cache_hit():
    async def run():
        port = SdkGenerationPort(FIXTURE_WORKSPACE)
        try:
            outline = await port.outline(SLUG)
            assert isinstance(outline, Outline)
            assert outline.strategic_frame in FRAMES
            assert outline.frame_rationale.strip()
            assert outline.resume_units, "expected at least one resume unit"
            assert all(u.unit_id.startswith("resume.") for u in outline.resume_units)

            # Two units on the persistent variant client: the 2nd must hit the cache.
            first, second = outline.resume_units[0], outline.resume_units[1]
            v1 = await port.variants(SLUG, first, n=4)
            assert v1, "expected variants for the first unit"
            assert all(v.text.strip() for v in v1)
            assert all(v.evidence_items for v in v1)

            await port.variants(SLUG, second, n=4)
            assert port.last_call is not None
            assert port.last_call.cache_read_tokens > 0, (
                f"expected cache hit, got call={port.last_call}"
            )
        finally:
            await port.aclose()

    asyncio.run(run())
