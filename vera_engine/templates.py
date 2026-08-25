"""Deterministic category-aware message templates."""

from __future__ import annotations

from typing import Any

from .models import CategoryContext, CustomerContext, MerchantContext
from .planner import MessagePlan
from .signals import NormalizedTrigger


def render_message(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
    customer: CustomerContext | None = None,
) -> tuple[str, list[str]]:
    if customer and trigger.scope == "customer":
        return _render_customer(merchant, trigger, plan, customer)
    return _render_merchant(category, merchant, trigger, plan)


def _render_customer(
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
    customer: CustomerContext,
) -> tuple[str, list[str]]:
    customer_name = str(customer.identity.get("name") or "there")
    merchant_name = str(merchant.identity.get("name") or "The clinic")
    facts = plan.facts
    if trigger.kind in {"recall_due", "appointment_tomorrow", "trial_followup"}:
        detail = _first_fact(facts, "customer_due_date", "customer_available_slots", "customer_next_session_options")
        body = f"Hi {customer_name}, {merchant_name} has a follow-up for you."
        if detail:
            body += f" {detail}."
        return f"{body} Want me to confirm it?", [customer_name, merchant_name, detail]
    if trigger.kind in {"customer_lapsed_soft", "customer_lapsed_hard"}:
        return f"Hi {customer_name}, {merchant_name} would be glad to welcome you back. Want me to book a visit?", [customer_name, merchant_name]
    return f"Hi {customer_name}, {merchant_name} has an update for you. Want me to confirm the next step?", [customer_name, merchant_name]


def _render_merchant(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
) -> tuple[str, list[str]]:
    owner = str(merchant.identity.get("owner_first_name") or merchant.identity.get("name") or "")
    facts = plan.facts
    if trigger.kind in {"research_digest", "cde_opportunity", "regulation_change"}:
        item = facts.get("digest_item", {})
        title = item.get("title") if isinstance(item, dict) else None
        source = item.get("source") if isinstance(item, dict) else None
        body = f"{_salutation(category, owner)}, a relevant {category.slug} update landed"
        if title:
            body += f": {title}"
        segment = item.get("patient_segment") if isinstance(item, dict) else None
        if segment == "high_risk_adults":
            count = merchant.customer_aggregate.get("high_risk_adult_count")
            if count:
                body += f" Your roster includes {count} high-risk adult patients"
        if source:
            body += f" ({source})"
        cta = "Want me to pull the source and draft a patient message?" if trigger.kind == "research_digest" else "Want me to prepare the next step?"
        return f"{body}. {cta}", [owner, title or "", source or ""]
    if trigger.kind in {"perf_dip", "seasonal_perf_dip"}:
        performance = facts.get("performance", {})
        metric = performance.get("metric") if isinstance(performance, dict) else None
        delta = performance.get("delta_pct") if isinstance(performance, dict) else None
        if metric and delta is not None:
            return f"{_salutation(category, owner)}, your {metric} is down {_percent(delta)} in the current trigger window. Want me to review the next action?", [owner, metric, _percent(delta)]
    if trigger.kind in {"perf_spike", "category_seasonal"}:
        offer = facts.get("offer")
        offer_title = offer.get("title") if isinstance(offer, dict) else None
        detail = f" Your active offer is {offer_title}." if offer_title else ""
        return f"{_salutation(category, owner)}, the current demand signal is worth acting on for {category.slug}.{detail} Want me to prepare a promotion?", [owner, offer_title or ""]
    topic = trigger.kind.replace("_", " ") or "current signal"
    return f"{_salutation(category, owner)}, I found a {topic} signal for your business. Want me to show the grounded details?", [owner, topic]


def _salutation(category: CategoryContext, owner: str) -> str:
    if category.slug == "dentists" and owner and not owner.casefold().startswith("dr"):
        return f"Dr. {owner}"
    return owner


def _first_fact(facts: dict[str, Any], *names: str) -> str:
    for name in names:
        value = facts.get(name)
        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                return str(value[0].get("label") or value[0].get("iso") or value[0])
            if value:
                return ", ".join(str(item) for item in value)
        elif value:
            return str(value)
    return ""


def _percent(value: Any) -> str:
    try:
        return f"{abs(float(value)) * 100:g}%"
    except (TypeError, ValueError):
        return str(value)