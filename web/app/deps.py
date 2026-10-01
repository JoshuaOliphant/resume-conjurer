# ABOUTME: Composition root — resolves which adapters back each port for this process.
# ABOUTME: Keyed on env (CONJURER_BACKEND, CONJURER_WORKSPACE, CONJURER_VERIFIER); routes never name a concrete adapter.
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
from app.adapters.verification_fake import FakeVerificationPort, NoVerificationPort
from app.adapters.verification_jev import JevVerificationPort
from app.adapters.workspace_fake import FakeWorkspaceRepository
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.ports import CompositionPort, GenerationPort, VerificationPort, WorkspaceRepository


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


def build_verification() -> VerificationPort:
    """Live checks claims with Jev only when ``CONJURER_VERIFIER=jev``; otherwise it checks nothing.

    Asking for Jev without ``TYPESAFE_API_KEY`` refuses to start rather than silently skipping.
    """
    if not is_live():
        return FakeVerificationPort()
    verifier = os.environ.get("CONJURER_VERIFIER", "")
    if not verifier:
        return NoVerificationPort()
    if verifier != "jev":
        raise RuntimeError(f"CONJURER_VERIFIER must be 'jev' or unset, not {verifier!r}.")
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CONJURER_VERIFIER=jev requires TYPESAFE_API_KEY; unset CONJURER_VERIFIER to run "
            "without the claim check."
        )
    return JevVerificationPort(api_key)


def build_composition() -> CompositionPort | None:
    # Live stitches+lints+exports the real workspace docs; fake has no workspace to stitch,
    # so it keeps the in-memory lint and the static export template (comp is None).
    if is_live():
        return ScriptCompositionPort(workspace_root())
    return None
