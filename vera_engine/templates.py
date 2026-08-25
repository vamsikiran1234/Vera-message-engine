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
    greeting = _customer_greeting(category_slug=merchant.category_slug, customer=customer)
    if trigger.kind in {"recall_due", "appointment_tomorrow", "trial_followup"}:
        detail = _first_fact(
            facts,
            "customer_available_slots", "available_slots", "customer_next_session_options",
            "next_session_options", "customer_due_date", "due_date",
        )
        if trigger.kind == "recall_due" and facts.get("service_due"):
            service = f"your {str(facts['service_due']).replace('_', ' ')} is due"
            detail = f"{service}; {detail}" if detail else service
        body = f"{greeting} {customer_name}, {merchant_name} has a follow-up for you."
        if detail:
            body += f" {detail}."
        offer = facts.get("offer")
        if isinstance(offer, dict) and offer.get("title"):
            body += f" Available: {offer['title']}."
        return f"{body} Want me to confirm it?", [customer_name, merchant_name, detail]
    if trigger.kind in {"customer_lapsed_soft", "customer_lapsed_hard"}:
        days = facts.get("days_since_last_visit")
        detail = f"It has been {days} days since your last visit. " if days else ""
        return f"{greeting} {customer_name}, {detail}{merchant_name} would be glad to welcome you back. Want me to book a visit?", [customer_name, merchant_name, str(days or "")]
    return f"{greeting} {customer_name}, {merchant_name} has an update for you. Want me to confirm the next step?", [customer_name, merchant_name]


def _customer_greeting(category_slug: str, customer: CustomerContext) -> str:
    language = str(customer.identity.get("language_pref", "")).casefold()
    if category_slug == "pharmacies" and language.startswith("hi"):
        return "Namaste"
    if category_slug == "gyms":
        return "Hi"
    return "Hi"


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
            count = plan.facts.get("high_risk_adult_count") or merchant.customer_aggregate.get("high_risk_adult_count")
            if count:
                body += f" Your roster includes {count} high-risk adult patients"
        if source:
            body += f" ({source})"
        if trigger.kind == "research_digest":
            cta = "Want me to pull the source and draft a patient message?"
        elif plan.cta == "confirm":
            cta = "Should I prepare the compliance checklist?"
        else:
            cta = "Want me to prepare the next step?"
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
    if trigger.kind in {"ipl_match_today", "festival", "local_event"}:
        event = facts.get("match") or facts.get("festival") or facts.get("event")
        event_time = facts.get("match_time_iso") or facts.get("date")
        offer = facts.get("offer")
        offer_title = offer.get("title") if isinstance(offer, dict) else None
        detail = str(event or "the current event")
        if event_time:
            detail += f" at {event_time}"
        if offer_title:
            detail += f". Your active offer is {offer_title}"
        return f"{_salutation(category, owner)}, {detail}. Want me to prepare the event promotion?", [owner, detail]
    if trigger.kind == "supply_alert":
        molecule = facts.get("molecule")
        batches = facts.get("affected_batches")
        manufacturer = facts.get("manufacturer")
        details = _join_facts(molecule, batches, manufacturer)
        return f"{_salutation(category, owner)}, a supply alert affects {details}. Want me to prepare the affected-customer review list?", [owner, details]
    if trigger.kind == "review_theme_emerged":
        theme = facts.get("theme")
        occurrences = facts.get("occurrences_30d")
        detail = f"{occurrences} reviews mention {theme}" if occurrences and theme else str(theme or "a review theme")
        return f"{_salutation(category, owner)}, {detail} in the last 30 days. Want me to draft a response plan?", [owner, detail]
    if trigger.kind == "competitor_opened":
        competitor = facts.get("competitor_name")
        distance = facts.get("distance_km")
        detail = f"{competitor} opened {distance} km away" if competitor and distance else "a nearby competitor opened"
        return f"{_salutation(category, owner)}, {detail}. Want me to review your current listing response?", [owner, detail]
    if trigger.kind == "renewal_due":
        days = facts.get("days_remaining")
        amount = facts.get("renewal_amount")
        detail = f"in {days} days" if days is not None else "soon"
        if amount is not None:
            detail += f" for ₹{amount}"
        return f"{_salutation(category, owner)}, your {merchant.subscription.get('plan', 'current')} plan renews {detail}. Want me to prepare the renewal details?", [owner, detail]
    if trigger.kind == "milestone_reached":
        metric = facts.get("metric")
        value = facts.get("value_now") or facts.get("milestone_value")
        detail = f"{value} {metric.replace('_', ' ')}" if metric and value is not None else "a new milestone"
        return f"{_salutation(category, owner)}, you are at {detail}. Want me to draft a milestone post?", [owner, detail]
    if trigger.kind == "festival_upcoming":
        festival = facts.get("festival")
        date = facts.get("date")
        detail = f"{festival} is on {date}" if festival and date else str(festival or "an upcoming occasion")
        return f"{_salutation(category, owner)}, {detail}. Want me to prepare one category-fit campaign idea?", [owner, detail]
    if trigger.kind == "gbp_unverified":
        path = facts.get("verification_path")
        detail = f"via {path}" if path else "through the available verification path"
        return f"{_salutation(category, owner)}, your business profile is still unverified {detail}. Want me to prepare the verification steps?", [owner, detail]
    if trigger.kind == "active_planning_intent":
        topic = facts.get("intent_topic", "your requested plan").replace("_", " ")
        return f"{_salutation(category, owner)}, I can continue the {topic} plan from your earlier request. Want me to draft the first version?", [owner, topic]
    if trigger.kind == "curious_ask_due":
        return f"{_salutation(category, owner)}, quick operator check for {category.slug}: which service or product was asked for most this week?", [owner, category.slug]
    if trigger.kind == "winback_eligible":
        days = facts.get("days_since_expiry")
        detail = f"{days} days since expiry" if days is not None else "your win-back signal"
        return f"{_salutation(category, owner)}, I found {detail} with a customer opportunity behind it. Want me to prepare a win-back draft?", [owner, detail]
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


def _join_facts(*values: Any) -> str:
    parts = []
    for value in values:
        if isinstance(value, list):
            parts.append(", ".join(str(item) for item in value))
        elif value:
            parts.append(str(value))
    return " / ".join(parts) or "the reported item"