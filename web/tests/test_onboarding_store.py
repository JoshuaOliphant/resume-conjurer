# ABOUTME: Tests persisted onboarding snapshots through real revision-checked document storage.
# ABOUTME: Covers stale writes, history, and malformed state without replacing the store.
import json

import pytest

from app.document_store import ConflictError
from app.onboarding import empty_state
from app.onboarding_store import OnboardingStore


def test_onboarding_state_survives_reload_and_stale_writes_preserve_newer_draft(tmp_path):
    store = OnboardingStore(tmp_path)
    state, revision = store.read()
    assert state == empty_state() and revision == ""
    first = store.save(state, revision)
    state["draft"] = "User's exact draft\r\n"
    second = store.save(state, first)
    assert second != first
    assert OnboardingStore(tmp_path).read() == (state, second)
    assert first in store.documents.history("onboarding.json")
    with pytest.raises(ConflictError):
        store.save(empty_state(), first)
    assert store.read()[0]["draft"] == "User's exact draft\r\n"


@pytest.mark.parametrize("value", [[], {}, {**empty_state(), "draft": []}])
def test_invalid_persisted_state_is_not_silently_reset(tmp_path, value):
    (tmp_path / "onboarding.json").write_text(json.dumps(value))
    with pytest.raises(ValueError, match="unreadable"):
        OnboardingStore(tmp_path).read()
