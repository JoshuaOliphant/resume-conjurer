# ABOUTME: Offline tests for the per-résumé metrics data model (cost, caching, performance).
# ABOUTME: Drives CallMetrics.from_result None-safety and RunMetrics derived properties.

from __future__ import annotations

from app.metrics import CallMetrics, RunMetrics, StepMetrics


class _StubResult:
    """A duck-typed stand-in for the SDK ResultMessage, for from_result tests."""

    def __init__(self, total_cost_usd, usage, duration_ms, duration_api_ms, num_turns):
        self.total_cost_usd = total_cost_usd
        self.usage = usage
        self.duration_ms = duration_ms
        self.duration_api_ms = duration_api_ms
        self.num_turns = num_turns


def test_from_result_reads_all_fields():
    result = _StubResult(
        total_cost_usd=0.0123,
        usage={
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 2000,
            "cache_creation_input_tokens": 30,
        },
        duration_ms=1200,
        duration_api_ms=900,
        num_turns=3,
    )
    call = CallMetrics.from_result(result)
    assert call.cost_usd == 0.0123
    assert call.input_tokens == 100
    assert call.output_tokens == 50
    assert call.cache_read_tokens == 2000
    assert call.cache_creation_tokens == 30
    assert call.duration_ms == 1200
    assert call.duration_api_ms == 900
    assert call.num_turns == 3


def test_from_result_treats_missing_usage_and_cost_as_zero():
    result = _StubResult(
        total_cost_usd=None,
        usage=None,
        duration_ms=0,
        duration_api_ms=0,
        num_turns=0,
    )
    call = CallMetrics.from_result(result)
    assert call.cost_usd == 0.0
    assert call.input_tokens == 0
    assert call.output_tokens == 0
    assert call.cache_read_tokens == 0
    assert call.cache_creation_tokens == 0


def test_from_result_treats_missing_usage_keys_as_zero():
    result = _StubResult(
        total_cost_usd=0.0,
        usage={"input_tokens": 5},  # other keys absent
        duration_ms=0,
        duration_api_ms=0,
        num_turns=0,
    )
    call = CallMetrics.from_result(result)
    assert call.input_tokens == 5
    assert call.output_tokens == 0
    assert call.cache_read_tokens == 0
    assert call.cache_creation_tokens == 0


def test_zero_is_an_all_zero_call():
    zero = CallMetrics.zero()
    assert zero.cost_usd == 0.0
    assert zero.input_tokens == 0
    assert zero.cache_read_tokens == 0
    assert zero.num_turns == 0


# --- RunMetrics derived properties -----------------------------------------


def _call(cost=0.0, ci=0, co=0, cr=0, cc=0, wall=0):
    return CallMetrics(
        cost_usd=cost,
        input_tokens=ci,
        output_tokens=co,
        cache_read_tokens=cr,
        cache_creation_tokens=cc,
        duration_ms=wall,
        duration_api_ms=wall,
        num_turns=1,
    )


def _populated() -> RunMetrics:
    return RunMetrics(
        slug="globex-staff-platform",
        steps=[
            StepMetrics(
                name="outline",
                wall_ms=500,
                call=_call(cost=0.10, ci=10, co=5, cr=0, cc=100),
            ),
            StepMetrics(
                name="cover_letter.opening",
                wall_ms=300,
                call=_call(cost=0.02, ci=20, co=8, cr=50, cc=10),
            ),
            StepMetrics(
                name="resume.fixture.bullet_1",
                wall_ms=200,
                call=_call(cost=0.03, ci=30, co=12, cr=70, cc=10),
            ),
        ],
    )


def test_run_metrics_totals_aggregate_across_steps():
    rm = _populated()
    assert rm.total_cost_usd == 0.15
    assert rm.total_input_tokens == 60
    assert rm.total_output_tokens == 25
    assert rm.total_cache_read == 120
    assert rm.total_cache_creation == 120
    assert rm.wall_ms == 1000


def test_line_count_excludes_the_outline_step():
    rm = _populated()
    assert rm.line_count == 2  # two non-outline steps


def test_cost_per_line_divides_total_by_lines():
    rm = _populated()
    assert rm.cost_per_line == 0.15 / 2


def test_cost_per_line_is_zero_with_no_lines():
    rm = RunMetrics(slug="s", steps=[])
    assert rm.line_count == 0
    assert rm.cost_per_line == 0.0


def test_cache_hit_pct_over_all_steps():
    rm = _populated()
    # 120 read / (120 read + 120 creation) = 50%
    assert rm.cache_hit_pct == 50.0


def test_cache_hit_pct_is_zero_when_denominator_zero():
    rm = RunMetrics(slug="s", steps=[])
    assert rm.cache_hit_pct == 0.0


def test_variant_cache_hit_pct_excludes_the_outline_step():
    rm = _populated()
    # Only the two non-outline steps: 120 read / (120 read + 20 creation) ~= 85.71%
    expected = 120 / (120 + 20) * 100
    assert rm.variant_cache_hit_pct == expected


def test_variant_cache_hit_pct_is_zero_when_no_variant_cache():
    rm = RunMetrics(
        slug="s",
        steps=[StepMetrics(name="outline", wall_ms=1, call=_call(cr=10, cc=10))],
    )
    # No non-outline steps, so the variant denominator is zero.
    assert rm.variant_cache_hit_pct == 0.0


# --- serialization ---------------------------------------------------------


def test_to_dict_round_trips_through_from_dict():
    rm = _populated()
    data = rm.to_dict()
    restored = RunMetrics.from_dict(data)
    assert restored == rm


def test_to_dict_carries_derived_totals_for_the_api():
    rm = _populated()
    data = rm.to_dict()
    assert data["slug"] == "globex-staff-platform"
    assert data["total_cost_usd"] == 0.15
    assert data["line_count"] == 2
    assert data["cache_hit_pct"] == 50.0
    assert len(data["steps"]) == 3
