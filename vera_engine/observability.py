"""Structured in-memory decision diagnostics for local evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class DecisionEvent:
    trigger_id: str
    merchant_id: str | None
    customer_id: str | None
    candidate_scores: tuple[dict[str, Any], ...] = ()
    selected_signal: str | None = None
    selected_action: str | None = None
    suppression_key: str | None = None
    validation_passed: bool = False
    validation_reasons: tuple[str, ...] = ()
    outcome: str = ""
    latency_ms: float = 0.0


@dataclass
class DecisionLogger:
    events: list[DecisionEvent] = field(default_factory=list)

    def record(self, event: DecisionEvent) -> None:
        self.events.append(event)


class DecisionTimer:
    def __enter__(self) -> "DecisionTimer":
        self.started = perf_counter()
        return self

    def elapsed_ms(self) -> float:
        return round((perf_counter() - self.started) * 1000, 3)