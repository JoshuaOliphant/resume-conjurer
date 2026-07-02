# ABOUTME: Per-résumé run metrics — cost, cache effectiveness, and performance as pure types.
# ABOUTME: CallMetrics reads the SDK ResultMessage None-safely; RunMetrics derives the headline figures.

"""Pure metrics types for one generation run.

A run is a sequence of agent calls — one ``outline`` call, then one per unit. Each call's
cost/token/cache/duration figures come from the SDK ``ResultMessage`` (read None-safely so
a missing field never crashes a run). :class:`RunMetrics` aggregates those into the figures
the UI surfaces: cost per résumé, cache effectiveness, and wall time.

These types hold no I/O and no SDK import; :meth:`CallMetrics.from_result` duck-reads the
ResultMessage's documented fields, so the metrics model stays free of the agent SDK and the
SDK adapter is the only place a real ResultMessage is touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CallMetrics:
    """Cost, tokens, caching, and timing for one agent call."""

    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    duration_ms: int = 0
    duration_api_ms: int = 0
    num_turns: int = 0

    @classmethod
    def zero(cls) -> CallMetrics:
        """An all-zero call, the fallback when a call produced no ResultMessage."""
        return cls()

    @classmethod
    def from_result(cls, result: Any) -> CallMetrics:
        """Read a CallMetrics from an SDK ResultMessage, treating missing fields as zero.

        ``result`` is duck-typed (the SDK ResultMessage), so a None usage, a missing usage
        key, or a None cost all read as zero rather than raising.
        """
        usage = getattr(result, "usage", None) or {}
        return cls(
            cost_usd=getattr(result, "total_cost_usd", None) or 0.0,
            input_tokens=usage.get("input_tokens") or 0,
            output_tokens=usage.get("output_tokens") or 0,
            cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
            cache_creation_tokens=usage.get("cache_creation_input_tokens") or 0,
            duration_ms=getattr(result, "duration_ms", None) or 0,
            duration_api_ms=getattr(result, "duration_api_ms", None) or 0,
            num_turns=getattr(result, "num_turns", None) or 0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_usd": self.cost_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "duration_ms": self.duration_ms,
            "duration_api_ms": self.duration_api_ms,
            "num_turns": self.num_turns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CallMetrics:
        return cls(
            cost_usd=data["cost_usd"],
            input_tokens=data["input_tokens"],
            output_tokens=data["output_tokens"],
            cache_read_tokens=data["cache_read_tokens"],
            cache_creation_tokens=data["cache_creation_tokens"],
            duration_ms=data["duration_ms"],
            duration_api_ms=data["duration_api_ms"],
            num_turns=data["num_turns"],
        )


@dataclass(frozen=True)
class StepMetrics:
    """One run step: the outline call (name="outline") or a unit's call (name=unit_id)."""

    name: str
    wall_ms: int
    call: CallMetrics

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "wall_ms": self.wall_ms, "call": self.call.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepMetrics:
        return cls(
            name=data["name"],
            wall_ms=data["wall_ms"],
            call=CallMetrics.from_dict(data["call"]),
        )


_OUTLINE = "outline"


@dataclass
class RunMetrics:
    """All steps of one run, with the derived headline figures the UI surfaces."""

    slug: str
    steps: list[StepMetrics] = field(default_factory=list)

    def add_step(self, step: StepMetrics) -> None:
        """The one sanctioned way to append a step (over mutating ``.steps`` directly)."""
        self.steps.append(step)

    @property
    def _variant_steps(self) -> list[StepMetrics]:
        # The per-unit steps: everything except the single outline call.
        return [s for s in self.steps if s.name != _OUTLINE]

    @property
    def total_cost_usd(self) -> float:
        return sum(s.call.cost_usd for s in self.steps)

    @property
    def total_input_tokens(self) -> int:
        return sum(s.call.input_tokens for s in self.steps)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.call.output_tokens for s in self.steps)

    @property
    def total_cache_read(self) -> int:
        return sum(s.call.cache_read_tokens for s in self.steps)

    @property
    def total_cache_creation(self) -> int:
        return sum(s.call.cache_creation_tokens for s in self.steps)

    @property
    def line_count(self) -> int:
        return len(self._variant_steps)

    @property
    def cost_per_line(self) -> float:
        lines = self.line_count
        if lines == 0:
            return 0.0
        return self.total_cost_usd / lines

    @property
    def wall_ms(self) -> int:
        return sum(s.wall_ms for s in self.steps)

    @staticmethod
    def _hit_pct(read: int, creation: int) -> float:
        denom = read + creation
        if denom == 0:
            return 0.0
        return read / denom * 100

    @property
    def cache_hit_pct(self) -> float:
        return self._hit_pct(self.total_cache_read, self.total_cache_creation)

    @property
    def variant_cache_hit_pct(self) -> float:
        # The cache hit rate over ONLY the per-unit steps. The outline call's huge framework
        # cache_read would otherwise mask whether the persistent variant client is warm.
        variant = self._variant_steps
        read = sum(s.call.cache_read_tokens for s in variant)
        creation = sum(s.call.cache_creation_tokens for s in variant)
        return self._hit_pct(read, creation)

    def to_dict(self) -> dict[str, Any]:
        # Raw fields (slug + steps) reconstruct the object; the derived totals ride along for
        # the JSON API and the template (from_dict ignores them and rebuilds from steps).
        return {
            "slug": self.slug,
            "steps": [s.to_dict() for s in self.steps],
            "total_cost_usd": self.total_cost_usd,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_read": self.total_cache_read,
            "total_cache_creation": self.total_cache_creation,
            "line_count": self.line_count,
            "cost_per_line": self.cost_per_line,
            "wall_ms": self.wall_ms,
            "cache_hit_pct": self.cache_hit_pct,
            "variant_cache_hit_pct": self.variant_cache_hit_pct,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunMetrics:
        return cls(
            slug=data["slug"],
            steps=[StepMetrics.from_dict(s) for s in data["steps"]],
        )
