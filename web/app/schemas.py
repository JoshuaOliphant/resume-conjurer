# ABOUTME: JSON Schema for the outline generation step, fed to the SDK via output_format.
# ABOUTME: Mirrors applications/<slug>/outline.json (plugins/.../references/pipeline.md) exactly.
"""The outline contract as a JSON Schema.

The live generation adapter passes this as ``output_format={"type":"json_schema",
"schema": OUTLINE_SCHEMA}`` so the SDK returns a validated dict in
``ResultMessage.structured_output`` (verified live; see web/IMPLEMENTATION_PLAN.md).
Keep the keys identical to the conjurer pipeline's outline.json so the web and CLI
paths share one contract.
"""

from __future__ import annotations

from typing import Any

_UNIT_ITEMS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "unit_id": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["unit_id", "description"],
}

OUTLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "strategic_frame": {
            "type": "string",
            "enum": ["scale", "friction", "conviction", "multiplier"],
        },
        "frame_rationale": {"type": "string"},
        "company": {"type": "string"},
        "role_title": {"type": "string"},
        "cover_letter_units": {"type": "array", "items": _UNIT_ITEMS},
        "resume_units": {"type": "array", "items": _UNIT_ITEMS},
    },
    "required": [
        "strategic_frame",
        "frame_rationale",
        "company",
        "role_title",
        "cover_letter_units",
        "resume_units",
    ],
}
