# ABOUTME: Exercises the real onboarding SDK adapter against an injected external client boundary.
# ABOUTME: Proves request permissions, single-call accounting, and unsuccessful result handling.
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from claude_agent_sdk.types import ResultMessage
from test_onboarding import ANSWERS, _payload

from app.onboarding import build_prompt, empty_state, source_lines, validate_glossary
from app.onboarding_sdk import OnboardingSdk

GLOSSARY_MASTER = Path(__file__).parent / "fixtures" / "glossary-master-resume.md"


def _result(payload=None, **values):
    return ResultMessage(subtype="success", duration_ms=15, duration_api_ms=10, is_error=False,
                         num_turns=2, session_id="synthetic", structured_output=_payload() if payload is None else payload,
                         total_cost_usd=0.012, usage={"input_tokens": 120, "output_tokens": 80}, **values)


class SdkBoundary:
    def __init__(self):
        self.calls = []
        self.options = []
        self.messages = [_result()]
        self.before_result = None

    def __call__(self, *, options):
        self.options.append(options)
        boundary = self

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def query(self, prompt):
                boundary.calls.append(prompt)

            async def receive_response(self):
                if boundary.before_result:
                    boundary.before_result()
                for message in boundary.messages:
                    yield message

        return Client()


def test_sdk_only_receives_reviewed_prompt_and_records_actual_measurements():
    boundary = SdkBoundary()
    boundary.messages.insert(0, SimpleNamespace(content="ignored intermediate response"))
    payload, metrics = asyncio.run(OnboardingSdk(boundary).draft("Exact reviewed synthetic text"))
    assert payload == _payload()
    assert boundary.calls == ["Exact reviewed synthetic text"]
    options = boundary.options[0]
    assert options.tools == options.allowed_tools == options.setting_sources == options.skills == options.plugins == []
    assert options.permission_mode == "dontAsk" and options.strict_mcp_config
    assert options.max_turns == 3 and options.max_budget_usd == 0.10
    assert options.output_format["schema"]["required"] == ["sections", "glossary"]
    assert metrics == {"elapsed_ms": metrics["elapsed_ms"], "input_tokens": 120, "output_tokens": 80, "cost_usd": 0.012}
    assert metrics["elapsed_ms"] >= 0


@pytest.mark.parametrize("messages", [[], [ResultMessage(subtype="error", duration_ms=1, duration_api_ms=1,
                                                          is_error=True, num_turns=1, session_id="synthetic")]])
def test_sdk_failure_does_not_return_a_draft(messages):
    boundary = SdkBoundary()
    boundary.messages = messages
    with pytest.raises(ValueError, match="did not complete"):
        asyncio.run(OnboardingSdk(boundary).draft("Synthetic input"))


def test_missing_usage_and_cost_are_reported_unavailable():
    boundary = SdkBoundary()
    boundary.messages = [ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                                      num_turns=1, session_id="synthetic", structured_output=_payload())]
    _, metrics = asyncio.run(OnboardingSdk(boundary).draft("Synthetic input"))
    assert metrics["cost_usd"] is metrics["input_tokens"] is metrics["output_tokens"] is None


@pytest.mark.live
def test_live_draft_proposes_internal_terms_but_not_public_technologies():
    master = GLOSSARY_MASTER.read_text()
    state = empty_state()
    state["answers"] = ANSWERS.copy()
    state["selected"] = [source for source in source_lines(master, "fixture", []) if "support team" in source["text"]]
    payload, _ = asyncio.run(OnboardingSdk().draft(build_prompt(state, master)))
    terms = {row["internal_term"].casefold() for row in validate_glossary(payload)}
    assert "mailapi" in terms
    assert terms.isdisjoint({"kafka", "kubernetes", "fastapi"})
