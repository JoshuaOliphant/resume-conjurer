# ABOUTME: Persists unaccepted onboarding snapshots and drafts with existing revision history.
# ABOUTME: Keeps onboarding state separate from accepted grimoire and career evidence documents.
from __future__ import annotations

import json
from pathlib import Path

from app.document_store import DocumentStore
from app.onboarding import empty_state


class OnboardingStore:
    def __init__(self, root: Path):
        self.documents = DocumentStore(root, names=frozenset({"onboarding.json"}))

    def read(self) -> tuple[dict, str]:
        text, revision = self.documents.read_with_revision("onboarding.json")
        if not text:
            return empty_state(), revision
        state = json.loads(text)
        defaults = empty_state()
        if not isinstance(state, dict) or any(key not in state or not isinstance(state[key], type(value)) for key, value in defaults.items()):
            raise ValueError("Onboarding state is unreadable; recover its revision history before continuing.")
        return state, revision

    def save(self, state: dict, revision: str) -> str:
        return self.documents.save("onboarding.json", json.dumps(state, ensure_ascii=False, indent=2), revision)
