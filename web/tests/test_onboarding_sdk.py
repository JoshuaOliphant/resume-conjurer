# ABOUTME: Exercises the real onboarding SDK adapter against an injected external client boundary.
# ABOUTME: Proves request permissions, single-call accounting, and unsuccessful result handling.
import asyncio
from types import SimpleNamespace

import pytest
from claude_agent_sdk.types import ResultMessage
from test_onboarding import _payload

from app.onboarding_sdk import OnboardingSdk


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
