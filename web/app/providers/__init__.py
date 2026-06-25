# ABOUTME: The ApplicationProvider port — the seam between the core and how an Application is built.
# ABOUTME: BACKEND.md's "replace one mock adapter with a real one" expressed as a typed contract.
"""Provider port for hydrating the domain `Application`.

The routes depend on this Protocol, not on any concrete source. Today the only
adapter is `FixtureProvider` (in-memory mock); wiring a live Claude Agent SDK
backend later means adding another adapter that satisfies the same contract — no
route or template changes. This is the documented hexagon seam, made real in code.
"""

from __future__ import annotations

from typing import Protocol

from app.domain import Application


class ApplicationProvider(Protocol):
    def get_application(self) -> Application: ...
