# ABOUTME: Composition root — resolves which adapters back each port for this process.
# ABOUTME: Keyed on env (CONJURER_BACKEND, CONJURER_WORKSPACE); routes never name a concrete adapter.
"""Where the ports get their concrete adapters.

One place resolves which backend (fake/offline vs live SDK) and which workspace, keyed on
env. The default is ``fake``, preserving the shipped editorial UI offline. Routes take a
``WorkspaceRepository`` / ``GenerationPort`` / ``CompositionPort`` and never name a concrete
adapter, so swapping one is a one-line change here.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.adapters.composition import ScriptCompositionPort
from app.adapters.generation_fake import FakeGenerationPort
from app.adapters.generation_sdk import SdkGenerationPort
from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.ports import CompositionPort, GenerationPort, WorkspaceRepository


def is_live() -> bool:
    return os.environ.get("CONJURER_BACKEND", "fake") == "live"


def workspace_root() -> Path:
    """The live workspace root, from ``CONJURER_WORKSPACE``.

    No silent fallback: a live backend with no workspace configured must fail loudly
    rather than default to the tracked test fixture directory, which a live run would
    then write generated JD/outline/variants/metrics into.
    """
    env = os.environ.get("CONJURER_WORKSPACE")
    if not env:
        raise RuntimeError(
            "CONJURER_BACKEND=live requires CONJURER_WORKSPACE to point at a workspace "
            "directory (grimoire.md, master-resume.md, applications/); refusing to guess."
        )
    return Path(env)


def build_repository() -> WorkspaceRepository:
    if is_live():
        return FsWorkspaceRepository(workspace_root())
    return FakeWorkspaceRepository()


def build_generation() -> GenerationPort:
    if is_live():
        return SdkGenerationPort(workspace_root())
    return FakeGenerationPort()


def build_composition() -> CompositionPort | None:
    # Live stitches+lints+exports the real workspace docs; fake has no workspace to stitch,
    # so it keeps the in-memory lint and the static export template (comp is None).
    if is_live():
        return ScriptCompositionPort(workspace_root())
    return None
