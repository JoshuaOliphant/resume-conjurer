# ABOUTME: The pipeline rail (Start → Outline → Curate → Review → Export) and the template context.
# ABOUTME: View concern only — the steps strip every screen renders, kept out of the route handlers.
"""Pipeline rail config and the shared template context.

Every screen renders the same five-step rail with one step marked active. That is
a presentation concern, not routing, so it lives here; routes call
``template_context(...)`` to fold the rail state into whatever else a page needs.
"""

from __future__ import annotations

from fastapi import Request

# The five pipeline steps, in order, for the rail.
STEPS = [
    ("entry", "Start", "/"),
    ("outline", "Outline", "/outline"),
    ("curate", "Curate", "/curate"),
    ("review", "Review", "/review"),
    ("export", "Export", "/export"),
]


def template_context(request: Request, active: str, **extra) -> dict:
    active_i = next((i for i, (key, _, _) in enumerate(STEPS) if key == active), 0)
    return {
        "request": request,
        "steps": STEPS,
        "active_step": active,
        "active_i": active_i,
        **extra,
    }
