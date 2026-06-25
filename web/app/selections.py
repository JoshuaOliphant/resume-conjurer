# ABOUTME: SelectionStore port + in-memory adapter for per-run curation picks (unit -> variant).
# ABOUTME: Replaces the module-global dict BACKEND.md flagged as unscoped; picks are keyed by session.
"""Where a run's curation picks live.

BACKEND.md names the old `SELECTIONS` module-level dict as a defect: "single-user,
lost on reload, not scoped to a run." The fix expressed here is a port plus a
scoped adapter — routes depend on the `SelectionStore` Protocol and address picks
by a session id, so the in-memory mock can later be swapped for a workspace-backed
store (BACKEND.md's `variants.md` persistence) without touching the routes.

The mock adapter is still in-memory, but it is now *scoped*: each browser session
gets its own pick set, so two people (or two tabs) no longer share state.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol


class SelectionStore(Protocol):
    """Per-session storage of one chosen variant id per unit."""

    def get(self, session_id: str, unit_id: str) -> str | None: ...
    def set(self, session_id: str, unit_id: str, variant_id: str) -> None: ...
    def all(self, session_id: str) -> dict[str, str]: ...
    def clear(self, session_id: str) -> None: ...


class InMemorySelectionStore:
    """A dict-of-dicts: session_id -> {unit_id -> variant_id}.

    Process-local and non-durable (fine for the prototype); scoped per session so
    picks don't leak between runs. Swap for a workspace-backed adapter to persist.
    """

    def __init__(self) -> None:
        self._by_session: dict[str, dict[str, str]] = defaultdict(dict)

    def get(self, session_id: str, unit_id: str) -> str | None:
        # Read-only: don't let a lookup mint an empty session via defaultdict.
        return self._by_session.get(session_id, {}).get(unit_id)

    def set(self, session_id: str, unit_id: str, variant_id: str) -> None:
        self._by_session[session_id][unit_id] = variant_id

    def all(self, session_id: str) -> dict[str, str]:
        return dict(self._by_session.get(session_id, {}))

    def clear(self, session_id: str) -> None:
        self._by_session.pop(session_id, None)

    def reset(self) -> None:
        """Drop every session. Test helper; not part of the port."""
        self._by_session.clear()
