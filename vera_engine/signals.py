"""Normalize trigger data and extract actionable, grounded signals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import CategoryContext, CustomerContext, MerchantContext, TriggerContext


@dataclass(frozen=True)
class NormalizedTrigger:
    trigger_id: str
    kind: str
    scope: str
    source: str
    urgency: int
    merchant_id: str
    customer_id: str | None
    facts: dict[str, Any] = field(default_factory=dict)
    is_placeholder: bool = False


@dataclass(frozen=True)
class Signal:
    name: str
    value: Any
    evidence: tuple[str, ...] = ()
    specificity: int = 0
    urgency: int = 0


def normalize_trigger(trigger: TriggerContext) -> NormalizedTrigger:
    payload = dict(trigger.payload)
    is_placeholder = payload.get("placeholder") is True
    facts = {
        key: value
        for key, value in payload.items()
        if key not in {"placeholder", "metric_or_topic"} and value not in (None, "", [])
    }
    return NormalizedTrigger(
        trigger_id=trigger.trigger_id,
        kind=trigger.kind,
        scope=trigger.scope,
        source=trigger.source,
        urgency=max(0, min(5, trigger.urgency)),
        merchant_id=trigger.merchant_id,
        customer_id=trigger.customer_id,
        facts=facts,
        is_placeholder=is_placeholder,
    )


def extract_signals(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    customer: CustomerContext | None = None,
) -> list[Signal]:
    """Return stable, evidence-backed signals ordered by extraction priority."""
    signals: list[Signal] = []
    payload = trigger.facts

    if trigger.kind in {"perf_dip", "seasonal_perf_dip"}:
        metric = payload.get("metric")
        delta = payload.get("delta_pct")
        if metric and isinstance(delta, (int, float)) and delta < 0:
            signals.append(Signal(
                name="performance_decline",
                value={"metric": metric, "delta_pct": delta},
                evidence=(f"trigger.payload.delta_pct={delta}", f"trigger.payload.metric={metric}"),
                specificity=3,
                urgency=trigger.urgency,
            ))
        if payload.get("is_expected_seasonal") is True:
            signals.append(Signal(
                name="expected_seasonal_decline",
                value=payload.get("season_note", True),
                evidence=("trigger.payload.is_expected_seasonal=true",),
                specificity=2,
                urgency=trigger.urgency,
            ))

    if trigger.kind in {"perf_spike", "category_seasonal"}:
        metric = payload.get("metric")
        delta = payload.get("delta_pct")
        if metric and isinstance(delta, (int, float)) and delta > 0:
            signals.append(Signal(
                name="performance_increase",
                value={"metric": metric, "delta_pct": delta},
                evidence=(f"trigger.payload.delta_pct={delta}", f"trigger.payload.metric={metric}"),
                specificity=3,
                urgency=trigger.urgency,
            ))
        trends = payload.get("trends")
        if isinstance(trends, list) and trends:
            signals.append(Signal(
                name="seasonal_demand_shift",
                value=trends,
                evidence=("trigger.payload.trends",),
                specificity=2,
                urgency=trigger.urgency,
            ))

    if trigger.kind in {"research_digest", "cde_opportunity", "regulation_change"}:
        item_id = payload.get("top_item_id") or payload.get("digest_item_id")
        if item_id:
            matching = next((item for item in category.digest if item.get("id") == item_id), None)
            if matching:
                signals.append(Signal(
                    name="category_digest_item",
                    value=matching,
                    evidence=(f"category.digest.id={item_id}",),
                    specificity=4,
                    urgency=trigger.urgency,
                ))
        if payload.get("deadline_iso"):
            signals.append(Signal(
                name="compliance_deadline",
                value=payload["deadline_iso"],
                evidence=("trigger.payload.deadline_iso",),
                specificity=4,
                urgency=trigger.urgency,
            ))

    if trigger.kind in {"recall_due", "chronic_refill_due", "appointment_tomorrow", "trial_followup"} and customer:
        if customer.customer_id == trigger.customer_id:
            signals.append(Signal(
                name="customer_followup",
                value=customer.state,
                evidence=(f"customer.state={customer.state}",),
                specificity=2,
                urgency=trigger.urgency,
            ))
        for key in ("due_date", "stock_runs_out_iso", "available_slots", "next_session_options", "molecule_list"):
            if payload.get(key):
                signals.append(Signal(
                    name=f"customer_{key}",
                    value=payload[key],
                    evidence=(f"trigger.payload.{key}",),
                    specificity=4,
                    urgency=trigger.urgency,
                ))

    if trigger.kind in {"customer_lapsed_soft", "customer_lapsed_hard", "winback_eligible"} and customer:
        signals.append(Signal(
            name="customer_lapse",
            value=customer.state,
            evidence=(f"customer.state={customer.state}",),
            specificity=2,
            urgency=trigger.urgency,
        ))
        if payload.get("days_since_last_visit"):
            signals.append(Signal(
                name="days_since_last_visit",
                value=payload["days_since_last_visit"],
                evidence=("trigger.payload.days_since_last_visit",),
                specificity=4,
                urgency=trigger.urgency,
            ))

    if trigger.kind == "review_theme_emerged" and payload.get("theme"):
        signals.append(Signal(
            name="review_theme",
            value=payload["theme"],
            evidence=("trigger.payload.theme",),
            specificity=3,
            urgency=trigger.urgency,
        ))

    if merchant.performance and trigger.kind in {"perf_dip", "perf_spike", "seasonal_perf_dip"}:
        metric = payload.get("metric")
        value = merchant.performance.get(metric) if metric else None
        if value is not None:
            signals.append(Signal(
                name="merchant_metric",
                value={"metric": metric, "value": value},
                evidence=(f"merchant.performance.{metric}={value}",),
                specificity=3,
                urgency=trigger.urgency,
            ))

    return signals