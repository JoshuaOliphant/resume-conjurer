# ABOUTME: Offline tests for the GenerationPort fake and the SDK adapter's pure helpers.
# ABOUTME: The SDK I/O itself is covered by the live test (test_generation_live.py).

import asyncio

from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.generation_sdk import (
    DEFAULT_MODEL,
    DEFAULT_PLUGIN_DIR,
    SdkGenerationPort,
    build_outline_prompt,
    build_variant_prompt,
    guard_variant_tool,
    outline_from_structured,
    variants_from_block,
)
from app.domain import FRAMES, Outline, OutlineUnit
from app.ports import GenerationPort
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny


# --- The fake --------------------------------------------------------------


def test_variant_tool_guard_allows_only_the_allowlist():
    # The variant client's can_use_tool guard is deny-by-default: only the read/search
    # and dispatch tools are allowed; everything else (including unknown built-ins and
    # any mcp__* tool) is denied.
    for allowed_name in ("Read", "Glob", "Grep", "Agent", "Task"):
        result = asyncio.run(guard_variant_tool(allowed_name, {"file_path": "master-resume.md"}, None))
        assert isinstance(result, PermissionResultAllow)
    for denied_name in (
        "Bash",
        "Write",
        "Edit",
        "MultiEdit",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
        "KillShell",
        "mcp__x__write",
        "BashOutput",  # an unknown built-in: denied because it is not on the allowlist
    ):
        result = asyncio.run(guard_variant_tool(denied_name, {"command": "rm -rf /"}, None))
        assert isinstance(result, PermissionResultDeny)


def test_fake_satisfies_generation_port():
    assert isinstance(FakeGenerationPort(), GenerationPort)


def test_sdk_adapter_constructs_and_conforms(tmp_path):
    # Construction is pure (no I/O); the SDK calls themselves are covered by the live test.
    port = SdkGenerationPort(tmp_path)
    assert port.workspace == tmp_path
    assert port.plugin_dir == DEFAULT_PLUGIN_DIR
    assert port.model == DEFAULT_MODEL
    assert port._variant_client is None
    assert isinstance(port, GenerationPort)


def test_fake_outline_reflects_the_fixture():
    outline = asyncio.run(FakeGenerationPort().outline("globex-staff-platform"))
    assert outline.strategic_frame == "scale"
    assert outline.frame_name == FRAMES["scale"]
    assert outline.company == "Globex"
    assert outline.role_title == "Staff Platform Engineer"
    # Two cover paragraphs and four resume bullets, convention-compliant ids.
    assert [u.unit_id for u in outline.cover_letter_units] == ["cover_letter.opening", "cover_letter.p2"]
    assert len(outline.resume_units) == 4
    assert all(u.unit_id.startswith("resume.") for u in outline.resume_units)


def test_fake_variants_for_known_unit_and_unknown_unit():
    fake = FakeGenerationPort()
    outline = asyncio.run(fake.outline("globex-staff-platform"))
    first = outline.cover_letter_units[0]
    variants = asyncio.run(fake.variants("globex-staff-platform", first, n=4))
    assert len(variants) == 4
    assert [v.id for v in variants] == [f"{first.unit_id}#{k}" for k in (1, 2, 3, 4)]
    assert variants[0].evidence()  # carries the fixture's resolved evidence
    # An outline unit the fake doesn't know yields no variants.
    unknown = OutlineUnit(unit_id="resume.nope.bullet_9", kind="resume_bullet", description="x")
    assert asyncio.run(fake.variants("globex-staff-platform", unknown, n=4)) == []


def test_fake_variants_respects_n():
    fake = FakeGenerationPort()
    outline = asyncio.run(fake.outline("globex-staff-platform"))
    variants = asyncio.run(fake.variants("globex-staff-platform", outline.resume_units[0], n=2))
    assert len(variants) == 2


def test_fake_last_call_is_none_before_any_call():
    assert FakeGenerationPort().last_call is None


def test_fake_records_synthetic_metrics_with_a_cold_then_warm_cache():
    fake = FakeGenerationPort()

    # The first call (outline) is a cold cache: it creates cache but reads none.
    asyncio.run(fake.outline("globex-staff-platform"))
    first = fake.last_call
    assert first is not None
    assert first.cost_usd > 0
    assert first.cache_creation_tokens > 0
    assert first.cache_read_tokens == 0
    assert first.duration_ms > 0

    # A subsequent variants call is warm: it reads from cache (the persistent-client design).
    outline = asyncio.run(fake.outline("globex-staff-platform"))
    asyncio.run(fake.variants("globex-staff-platform", outline.resume_units[0], n=2))
    warm = fake.last_call
    assert warm is not None
    assert warm.cache_read_tokens > 0
    assert warm.cache_creation_tokens < first.cache_creation_tokens


# --- SDK adapter pure helpers ---------------------------------------------


def test_build_outline_prompt_mentions_slug_and_frames():
    prompt = build_outline_prompt("globex-staff-platform")
    assert "applications/globex-staff-platform/jd.txt" in prompt
    assert "scale" in prompt and "multiplier" in prompt
    assert "Do not generate variants" in prompt


def test_build_variant_prompt_dispatches_the_subagent():
    unit = OutlineUnit(unit_id="resume.acme.bullet_1", kind="resume_bullet", description="Lead bullet")
    prompt = build_variant_prompt(unit, n=4)
    assert "conjurer:variant-generator" in prompt
    assert "resume.acme.bullet_1" in prompt
    assert "Lead bullet" in prompt


def test_outline_from_structured_maps_kinds_and_units():
    data = {
        "strategic_frame": "multiplier",
        "frame_rationale": "leverage over many teams",
        "company": "Globex",
        "role_title": "Staff Platform Engineer",
        "cover_letter_units": [{"unit_id": "cover_letter.opening", "description": "open"}],
        "resume_units": [
            {"unit_id": "resume.northwind.billing.bullet_1", "description": "headline"},
            {"unit_id": "resume.northwind.tooling.bullet_1", "description": "platform"},
        ],
    }
    outline = outline_from_structured(data)
    assert isinstance(outline, Outline)
    assert outline.strategic_frame == "multiplier"
    assert outline.cover_letter_units[0].kind == "cover_paragraph"
    assert all(u.kind == "resume_bullet" for u in outline.resume_units)
    assert [u.unit_id for u in outline.units] == [
        "cover_letter.opening",
        "resume.northwind.billing.bullet_1",
        "resume.northwind.tooling.bullet_1",
    ]


def test_variants_from_block_parses_citations_and_ids():
    unit = OutlineUnit(
        unit_id="resume.northwind.billing.bullet_1", kind="resume_bullet", description="headline"
    )
    block = (
        "Sure, dispatching the agent now.\n"
        "## Unit: resume.northwind.billing.bullet_1\n"
        "<!-- conjurer:unit id=resume.northwind.billing.bullet_1 -->\n"
        "*headline*\n\n"
        "### Variant 1: master-resume.md L9\n\n"
        "- Architected the billing-platform migration to event-driven services.\n\n"
        "*Axis: outcome-led*\n\n"
        "- [ ] Pick\n\n"
        "### Variant 2: master-resume.md L11\n\n"
        "- Led the platform migration onto an event-driven backbone.\n\n"
        "*Axis: ownership-led*\n\n"
        "- [ ] Pick\n"
    )
    variants = variants_from_block(block, unit)
    assert [v.id for v in variants] == [
        "resume.northwind.billing.bullet_1#1",
        "resume.northwind.billing.bullet_1#2",
    ]
    assert variants[0].evidence_items[0].id == "master-resume.md L9"
    assert "Architected the billing-platform migration" in variants[0].text
    assert "Axis" not in variants[0].text and "Pick" not in variants[0].text


def test_variants_from_block_skips_empty_and_defaults_missing_citation():
    unit = OutlineUnit(unit_id="cover_letter.opening", kind="cover_paragraph", description="open")
    block = (
        "### Variant 1: \n\n"
        "I led the billing migration that took invoicing from 40s to under 2s.\n\n"
        "- [ ] Pick\n\n"
        "### Variant 2: master-resume.md L3\n\n\n"  # empty body -> skipped
        "- [ ] Pick\n"
    )
    variants = variants_from_block(block, unit)
    assert len(variants) == 1
    assert variants[0].evidence_items[0].id == "master-resume.md"


def test_variants_from_block_final_variant_multiline_to_end_of_string():
    # A final variant whose body spans multiple lines and ends at end-of-string (no trailing
    # Axis or Pick line) must be captured whole by the \Z alternative in _VARIANT_RE.
    unit = OutlineUnit(
        unit_id="resume.northwind.billing.bullet_1", kind="resume_bullet", description="headline"
    )
    block = (
        "## Unit: resume.northwind.billing.bullet_1\n"
        "### Variant 1: master-resume.md L16\n\n"
        "- Led the billing migration to event-driven services.\n\n"
        "*Axis: outcome-led*\n\n"
        "- [ ] Pick\n\n"
        "### Variant 2: master-resume.md L17\n\n"
        "- Rolled the new billing backbone out across three regions\n"
        "  with zero customer-visible downtime, then owned the on-call\n"
        "  rotation that followed."  # no trailing newline, Axis, or Pick
    )
    variants = variants_from_block(block, unit)
    assert [v.id for v in variants] == [
        "resume.northwind.billing.bullet_1#1",
        "resume.northwind.billing.bullet_1#2",
    ]
    # The whole multi-line body of the final variant survives to end-of-string.
    assert "across three regions" in variants[1].text
    assert "rotation that followed." in variants[1].text
    assert variants[1].evidence_items[0].id == "master-resume.md L17"
