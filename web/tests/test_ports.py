# ABOUTME: Conformance tests — the concrete adapters satisfy the hexagonal port Protocols.
# ABOUTME: Importing app.ports here also exercises the contract module so it is covered.

from pathlib import Path

import pytest

from app.adapters.composition import ScriptCompositionPort
from app.adapters.verification_fake import FakeVerificationPort, NoVerificationPort
from app.adapters.workspace_fs import FsWorkspaceRepository
from app.ports import CompositionPort, GenerationPort, VerificationPort, WorkspaceRepository

FIXTURE = Path(__file__).parent / "fixtures" / "workspace"


def test_fs_repository_satisfies_workspace_repository():
    assert isinstance(FsWorkspaceRepository(FIXTURE), WorkspaceRepository)


def test_script_composition_satisfies_composition_port():
    assert isinstance(ScriptCompositionPort(FIXTURE), CompositionPort)


def test_generation_port_protocol_surface():
    # The live/fake GenerationPort adapters arrive in Phase 3; until then, assert the
    # contract's method surface exists (and import-cover the module).
    assert hasattr(GenerationPort, "outline")
    assert hasattr(GenerationPort, "variants")


@pytest.mark.parametrize(
    "verifier",
    [
        pytest.param(FakeVerificationPort(), id="fake"),
        pytest.param(NoVerificationPort(), id="no-op"),
    ],
)
def test_verification_adapters_satisfy_verification_port(verifier):
    assert isinstance(verifier, VerificationPort)
