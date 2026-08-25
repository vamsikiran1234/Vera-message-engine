"""Deterministic evidence selection stage.

Sits between candidate ranking and message planning.  Its job is to choose
the 2-3 strongest *grounded* facts that are relevant to the selected action
and to translate raw internal signal names into merchant-facing text so that
no internal terminology leaks into the rendered message.

Rules:
  - Only surfaces facts that are directly present in the context objects.
  - Translates signals like ``ctr_below_peer_median`` into human sentences
    using actual numeric values when those values are available.
  - Does NOT invent counts, percentages, or dates that are not in the context.
  - Returns an ``EvidenceBundle`` that callers merge into ``CandidateAction.facts``
    before the plan is built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import CategoryContext, CustomerContext, MerchantContext
from .signals import NormalizedTrigger


# ---------------------------------------------------------------------------
# Signal name → human-readable description (no numeric values, pure label)
# ---------------------------------------------------------------------------

_SIGNAL_LABELS: dict[str, str] = {
    "stale_posts": "Google posts are out of date",
    "ctr_below_peer_median": "click-through rate is below category peers",
    "high_risk_adult_cohort": "clinic has a high-risk adult patient cohort",
    "engaged_in_last_48h": "merchant engaged recently",
    "new_merchant": "recently joined",
    "trial_ending_soon": "trial is ending soon",
    "ipl_eligible_locality": "locality sees IPL-driven demand",
    "winback_eligible": "subscription is eligible for renewal",
    "perf_dip_post_expiry": "performance dipped after subscription expired",
    "dormant_with_vera_38d": "no conversation in 38 days",
    "above_peer_calls": "call volume is above category peers",
    "compliance_aware": "pharmacy is compliance-aware",
    "high_repeat_rate": "strong repeat-customer rate",
}


def _parse_signal(raw: str) -> tuple[str, str | None]:
    """Return (base_name, embedded_value) for signals like 'stale_posts:22d'."""
    if ":" in raw:
        parts = raw.split(":", 1)
        return parts[0], parts[1]
    return raw, None


def _format_signal(raw: str, merchant: MerchantContext, category: CategoryContext) -> str | None:
    """
    Translate a raw internal signal string into a merchant-facing sentence.

    Returns None if the signal cannot be grounded (missing numeric context).
    Never invents numbers.
    """
    base, embedded = _parse_signal(raw)

    if base == "stale_posts":
        # embedded value may be '22d'; also check conversation_history recency
        if embedded:
            days = embedded.rstrip("d")
            if days.isdigit():
                return f"last Google post was {days} days ago"
        return "Google posts are out of date"

    if base == "ctr_below_peer_median":
        merchant_ctr = merchant.performance.get("ctr")
        peer_ctr = category.peer_stats.get("avg_ctr") if category.peer_stats else None
        if merchant_ctr is not None and peer_ctr is not None:
            return (
                f"your CTR is {_pct(merchant_ctr)}, "
                f"below the {_pct(peer_ctr)} category peer median"
            )
        return "click-through rate is below category peers"

    if base == "above_peer_calls":
        merchant_calls = merchant.performance.get("calls")
        peer_calls = category.peer_stats.get("avg_calls_30d") if category.peer_stats else None
        if merchant_calls is not None and peer_calls is not None:
            return (
                f"your calls ({merchant_calls}/mo) are above the "
                f"{peer_calls} category peer median"
            )
        return "call volume is above category peers"

    if base == "high_risk_adult_cohort":
        count = merchant.customer_aggregate.get("high_risk_adult_count")
        if count is not None:
            return f"your roster includes {count} high-risk adult patients"
        return None  # cannot ground — suppress

    if base == "perf_dip_post_expiry":
        views = merchant.performance.get("views")
        if views is not None:
            return f"profile views are at {views} this month"
        return "profile performance has dipped since subscription expired"

    if base == "dormant_with_vera_38d":
        # The trigger payload carries the exact number; don't duplicate from signal
        return None  # handled via trigger payload, skip to avoid duplication

    # Fall back to generic label if one exists; skip unknown signals
    return _SIGNAL_LABELS.get(base)


def _pct(value: float) -> str:
    """Format a decimal fraction as a percentage string, e.g. 0.021 → '2.1%'."""
    return f"{value * 100:g}%"


# ---------------------------------------------------------------------------
# Evidence bundle
# ---------------------------------------------------------------------------

@dataclass
class EvidenceBundle:
    """Enriched facts to be merged into plan.facts before rendering."""

    # Human-readable translated signal sentences (max 2)
    signal_sentences: list[str] = field(default_factory=list)

    # Peer comparison facts (only when both merchant and peer values are present)
    peer_comparison: dict[str, Any] = field(default_factory=dict)

    # Merchant performance actuals (only the metric(s) relevant to the trigger)
    performance_actuals: dict[str, Any] = field(default_factory=dict)

    # Extra structured facts (e.g. lapsed_customers_added_since_expiry)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_facts_patch(self) -> dict[str, Any]:
        """Return a dict that callers can merge into candidate.facts."""
        patch: dict[str, Any] = {}
        if self.signal_sentences:
            patch["evidence_signals"] = self.signal_sentences
        if self.peer_comparison:
            patch["peer_comparison"] = self.peer_comparison
        if self.performance_actuals:
            patch["performance_actuals"] = self.performance_actuals
        patch.update(self.extra)
        return patch


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_evidence(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    candidate_facts: dict[str, Any],
    customer: CustomerContext | None = None,
) -> EvidenceBundle:
    """
    Choose the 2-3 strongest grounded facts for the selected action.

    Called after ranking, before build_message_plan.  Returns an EvidenceBundle
    whose ``to_facts_patch()`` the caller merges into candidate.facts.
    """
    bundle = EvidenceBundle()

    # --- 1. Translate relevant merchant signals (max 2, skip ungroundable) ---
    translated: list[str] = []
    for raw in merchant.signals:
        if len(translated) >= 2:
            break
        sentence = _format_signal(str(raw), merchant, category)
        if sentence:
            translated.append(sentence)
    bundle.signal_sentences = translated

    # --- 2. Peer comparison (only when merchant has the matching metric) ---
    peer = category.peer_stats
    if peer:
        trigger_metric = trigger.facts.get("metric")  # e.g. "calls", "views", "ctr"

        # Always expose CTR comparison when available — it's the most actionable peer stat
        merchant_ctr = merchant.performance.get("ctr")
        peer_ctr = peer.get("avg_ctr")
        if merchant_ctr is not None and peer_ctr is not None:
            bundle.peer_comparison["ctr"] = {
                "merchant": merchant_ctr,
                "peer_median": peer_ctr,
                "merchant_str": _pct(merchant_ctr),
                "peer_str": _pct(peer_ctr),
            }

        # Expose the trigger-specific metric comparison when different from CTR
        if trigger_metric and trigger_metric != "ctr":
            peer_key = f"avg_{trigger_metric}_30d"
            merchant_val = merchant.performance.get(trigger_metric)
            peer_val = peer.get(peer_key)
            if merchant_val is not None and peer_val is not None:
                bundle.peer_comparison[trigger_metric] = {
                    "merchant": merchant_val,
                    "peer_median": peer_val,
                }

    # --- 3. Performance actuals (metric relevant to the trigger, plus 7d delta) ---
    trigger_metric = trigger.facts.get("metric")
    if trigger_metric:
        actual = merchant.performance.get(trigger_metric)
        if actual is not None:
            bundle.performance_actuals["current_value"] = actual
            bundle.performance_actuals["metric"] = trigger_metric

        delta_7d = merchant.performance.get("delta_7d", {})
        delta_key = f"{trigger_metric}_pct"
        delta_val = delta_7d.get(delta_key)
        if delta_val is not None:
            bundle.performance_actuals["delta_7d_pct"] = delta_val

    # --- 4. Trigger-kind–specific extra facts ---
    _enrich_by_kind(trigger, merchant, category, bundle)

    return bundle


def _enrich_by_kind(
    trigger: NormalizedTrigger,
    merchant: MerchantContext,
    category: CategoryContext,
    bundle: EvidenceBundle,
) -> None:
    """Add trigger-kind–specific grounded facts to the bundle."""
    facts = trigger.facts
    kind = trigger.kind

    if kind == "winback_eligible":
        lapsed_added = facts.get("lapsed_customers_added_since_expiry")
        perf_dip = facts.get("perf_dip_pct")
        if lapsed_added is not None:
            bundle.extra["lapsed_customers_added_since_expiry"] = lapsed_added
        if perf_dip is not None:
            bundle.extra["perf_dip_pct"] = perf_dip

    elif kind == "dormant_with_vera":
        last_topic = facts.get("last_topic")
        if last_topic:
            bundle.extra["last_conversation_topic"] = str(last_topic).replace("_", " ")

    elif kind == "competitor_opened":
        their_offer = facts.get("their_offer")
        if their_offer:
            bundle.extra["competitor_offer"] = their_offer

    elif kind == "milestone_reached":
        is_imminent = facts.get("is_imminent")
        milestone_value = facts.get("milestone_value")
        value_now = facts.get("value_now")
        if is_imminent and milestone_value and value_now is not None:
            bundle.extra["milestone_gap"] = milestone_value - value_now

    elif kind in {"festival_upcoming", "festival"}:
        days_until = facts.get("days_until")
        if days_until is not None:
            bundle.extra["days_until_festival"] = days_until

    elif kind in {"perf_dip", "seasonal_perf_dip"}:
        vs_baseline = facts.get("vs_baseline")
        if vs_baseline is not None:
            bundle.performance_actuals["vs_baseline"] = vs_baseline

    elif kind in {"curious_ask_due"}:
        # Provide the top-searched query for this category as context
        peer = category.peer_stats
        if peer:
            avg_views = peer.get("avg_views_30d")
            if avg_views is not None:
                bundle.extra["peer_avg_views"] = avg_views
        trend = category.trend_signals
        if trend and isinstance(trend, list) and trend:
            top = trend[0]
            query = top.get("query")
            delta = top.get("delta_yoy")
            if query and delta is not None:
                bundle.extra["top_trend_query"] = query
                bundle.extra["top_trend_delta_yoy"] = delta
