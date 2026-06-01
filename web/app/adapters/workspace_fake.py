# ABOUTME: In-memory WorkspaceRepository for the default offline config.
# ABOUTME: Serves the rich data.py fixture application and keeps picks in a per-slug dict.

"""A fixture-backed, in-memory :class:`WorkspaceRepository`.

This is the repository half of the default ``fake`` composition. It preserves the
shipped editorial UI exactly: ``load_application`` returns the same rich, evidence-resolved
``Application`` the route tests have always rendered (from :mod:`app.data`), and picks live
in a process-local dict instead of on disk.

The generation-persistence methods (``load_inputs`` / ``save_outline`` / ``load_outline`` /
``save_variants``) belong to the live filesystem flow only; here they raise
``NotImplementedError`` (a line the coverage config excludes). The fake still satisfies the
``WorkspaceRepository`` Protocol because every method name is present.
"""

from __future__ import annotations

from app.data import get_application
from app.domain import Application, Outline, Unit, WorkspaceInputs


class FakeWorkspaceRepository:
    """Serves the fixture Application and stores picks in memory, keyed by slug."""

    def __init__(self) -> None:
        # slug -> {unit_id: variant_id}; exactly one pick per unit, like variants.md.
        self._picks: dict[str, dict[str, str]] = {}

    # --- generation persistence (live-only; unused offline) ----------------

    def load_inputs(self, slug: str) -> WorkspaceInputs:
        raise NotImplementedError

    def save_jd(self, slug: str, jd: str) -> None:
        raise NotImplementedError

    def save_outline(self, slug: str, outline: Outline) -> None:
        raise NotImplementedError

    def load_outline(self, slug: str) -> Outline | None:
        raise NotImplementedError

    def save_variants(self, slug: str, units: list[Unit]) -> None:
        raise NotImplementedError

    # --- picks -------------------------------------------------------------

    def set_pick(self, slug: str, unit_id: str, variant_id: str) -> None:
        self._picks.setdefault(slug, {})[unit_id] = variant_id

    def get_picks(self, slug: str) -> dict[str, str]:
        return dict(self._picks.get(slug, {}))

    def clear(self, slug: str) -> None:
        """Drop every pick for ``slug`` (the offline equivalent of /reset)."""
        self._picks.pop(slug, None)

    # --- hydration ---------------------------------------------------------

    def load_application(self, slug: str) -> Application:
        return get_application()
