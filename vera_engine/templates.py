"""Deterministic category-aware message templates.

Rules:
  - No internal Vera terminology in any rendered string (no 'trigger', 'candidate',
    'signal', 'operator check', 'suppression key', 'ranking', 'decision score').
  - Numbers in the message body must come from plan.facts (which is populated from
    the context objects), never from literals invented in this file.
  - Customer-facing messages are warm, personal, and never expose system concepts.
"""

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


# ---------------------------------------------------------------------------
# Customer-facing renderer
# ---------------------------------------------------------------------------

def _render_customer(
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
    customer: CustomerContext,
) -> tuple[str, list[str]]:
    customer_name = str(customer.identity.get("name") or "there")
    merchant_name = str(merchant.identity.get("name") or "us")
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
        return (
            f"{greeting} {customer_name}, {detail}"
            f"{merchant_name} would be glad to welcome you back. "
            f"Want me to book a visit?",
            [customer_name, merchant_name, str(days or "")],
        )

    # Generic customer fallback — no internal vocabulary
    return (
        f"{greeting} {customer_name}, {merchant_name} has a note for you. "
        f"Want me to confirm the next step?",
        [customer_name, merchant_name],
    )


def _customer_greeting(category_slug: str, customer: CustomerContext) -> str:
    language = str(customer.identity.get("language_pref", "")).casefold()
    if category_slug == "pharmacies" and language.startswith("hi"):
        return "Namaste"
    return "Hi"


# ---------------------------------------------------------------------------
# Merchant-facing renderer
# ---------------------------------------------------------------------------

def _render_merchant(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
) -> tuple[str, list[str]]:
    owner = str(merchant.identity.get("owner_first_name") or merchant.identity.get("name") or "")
    facts = plan.facts
    sal = _salutation(category, owner)

    # --- Objective-based overrides (take precedence over trigger.kind) ---

    if plan.objective == "improve_listing":
        performance = facts.get("performance", {})
        metric = performance.get("metric", "performance") if isinstance(performance, dict) else "performance"
        peer_ctr_str = _peer_ctr_sentence(facts)
        detail = f"your {metric} is under pressure"
        if peer_ctr_str:
            detail = peer_ctr_str
        return (
            f"{sal}, {detail} — your listing needs a refresh to close the gap. "
            f"Want me to draft the update?",
            [owner, metric],
        )

    if plan.objective == "reactivate_customers":
        count = facts.get("lapsed_customers")
        offer = facts.get("offer", {})
        title = offer.get("title") if isinstance(offer, dict) else None
        detail = f"{count} customers have lapsed" if count else "some customers have lapsed"
        if title:
            detail += f", and {title} is active"
        return (
            f"{sal}, {detail}. Want me to draft a customer win-back message?",
            [owner, str(count or ""), title or ""],
        )

    if plan.objective == "plan_seasonal_campaign":
        festival = facts.get("festival") or "the upcoming occasion"
        offer = facts.get("offer", {})
        title = offer.get("title") if isinstance(offer, dict) else None
        detail = f"{festival} is a fit for {title}" if title else str(festival)
        return (
            f"{sal}, {detail}. Want me to draft a category-fit campaign?",
            [owner, str(festival), title or ""],
        )

    if plan.objective == "prepare_content":
        # For curious_ask_due, dispatch to the dedicated renderer even if prepare_content was selected
        if trigger.kind == "curious_ask_due":
            return _render_curious_ask(sal, category, merchant, facts)
        intent = facts.get("intent", {})
        topic = intent.get("intent_topic") if isinstance(intent, dict) else None
        topic = str(topic or "the requested topic").replace("_", " ")
        return (
            f"{sal}, I picked up your earlier request about {topic}. "
            f"Want me to draft the first version now?",
            [owner, topic],
        )

    if plan.objective == "restart_merchant_conversation":
        days = facts.get("days_inactive")
        peer_ctr_str = _peer_ctr_sentence(facts)
        if peer_ctr_str and days:
            return (
                f"{sal}, we have not spoken in {days} days. Meanwhile, {peer_ctr_str}. "
                f"Want me to share one growth idea to act on this week?",
                [owner, str(days)],
            )
        return (
            f"{sal}, we have not spoken in {days} days. "
            f"Want me to send one useful growth idea for your business?",
            [owner, str(days or "")],
        )

    # --- Trigger-kind dispatch ---

    if trigger.kind in {"research_digest", "cde_opportunity", "regulation_change"}:
        return _render_digest(sal, category, merchant, trigger, facts, plan)

    if trigger.kind in {"perf_dip", "seasonal_perf_dip"}:
        return _render_perf_dip(sal, category, trigger, facts, plan)

    if trigger.kind in {"perf_spike", "category_seasonal"}:
        return _render_perf_spike(sal, category, trigger, facts)

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
        return (
            f"{sal}, {detail}. Want me to prepare the event promotion?",
            [owner, detail],
        )

    if trigger.kind == "supply_alert":
        molecule = facts.get("molecule")
        batches = facts.get("affected_batches")
        manufacturer = facts.get("manufacturer")
        details = _join_facts(molecule, batches, manufacturer)
        return (
            f"{sal}, a supply alert affects {details}. "
            f"Want me to prepare the affected-customer review list?",
            [owner, details],
        )

    if trigger.kind == "review_theme_emerged":
        theme = facts.get("theme")
        occurrences = facts.get("occurrences_30d")
        detail = f"{occurrences} reviews mention {theme}" if occurrences and theme else str(theme or "a review theme")
        return (
            f"{sal}, {detail} in the last 30 days. Want me to draft a response plan?",
            [owner, detail],
        )

    if trigger.kind == "competitor_opened":
        competitor = facts.get("competitor_name")
        distance = facts.get("distance_km")
        their_offer = facts.get("their_offer") or facts.get("competitor_offer")
        detail = f"{competitor} opened {distance} km away" if competitor and distance else "a nearby competitor opened"
        offer_note = f" They are advertising {their_offer}." if their_offer else ""
        peer_ctr_str = _peer_ctr_sentence(facts)
        position_note = f" Your current {peer_ctr_str}." if peer_ctr_str else ""
        return (
            f"{sal}, {detail}.{offer_note}{position_note} "
            f"Want me to review your listing and draft a counter-position?",
            [owner, detail],
        )

    if trigger.kind == "renewal_due":
        days = facts.get("days_remaining")
        amount = facts.get("renewal_amount")
        detail = f"in {days} days" if days is not None else "soon"
        if amount is not None:
            detail += f" for ₹{amount}"
        return (
            f"{sal}, your {merchant.subscription.get('plan', 'current')} plan renews {detail}. "
            f"Want me to prepare the renewal details?",
            [owner, detail],
        )

    if trigger.kind == "milestone_reached":
        return _render_milestone(sal, facts)

    if trigger.kind == "festival_upcoming":
        return _render_festival_upcoming(sal, facts)

    if trigger.kind == "gbp_unverified":
        path = facts.get("verification_path")
        detail = f"via {path}" if path else "through the available verification path"
        return (
            f"{sal}, your business profile is still unverified {detail}. "
            f"Want me to prepare the verification steps?",
            [owner, detail],
        )

    if trigger.kind == "active_planning_intent":
        topic = facts.get("intent_topic", "your requested plan").replace("_", " ")
        return (
            f"{sal}, I can continue the {topic} plan from your earlier request. "
            f"Want me to draft the first version?",
            [owner, topic],
        )

    if trigger.kind == "curious_ask_due":
        return _render_curious_ask(sal, category, merchant, facts)

    if trigger.kind == "winback_eligible":
        return _render_winback(sal, category, merchant, facts)

    if trigger.kind == "dormant_with_vera":
        days = facts.get("days_since_last_merchant_message") or facts.get("days_inactive")
        peer_ctr_str = _peer_ctr_sentence(facts)
        detail = f"in {days} days" if days is not None else "recently"
        if peer_ctr_str:
            return (
                f"{sal}, we have not spoken {detail}. Meanwhile, {peer_ctr_str}. "
                f"Want me to share one growth idea to act on this week?",
                [owner, str(days or "")],
            )
        return (
            f"{sal}, we have not spoken {detail}. "
            f"Want me to share one growth idea for your business this week?",
            [owner, str(days or "")],
        )

    # Generic fallback — still clean, no internal vocabulary
    topic = trigger.kind.replace("_", " ") if trigger.kind else "your business"
    return (
        f"{sal}, I have an update on {topic} worth reviewing. "
        f"Want me to show the details?",
        [owner, topic],
    )


# ---------------------------------------------------------------------------
# Specialised render helpers
# ---------------------------------------------------------------------------

def _render_digest(
    sal: str,
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    facts: dict[str, Any],
    plan: MessagePlan,
) -> tuple[str, list[str]]:
    item = facts.get("digest_item", {})
    title = item.get("title") if isinstance(item, dict) else None
    source = item.get("source") if isinstance(item, dict) else None
    body = f"{sal}, a relevant {category.slug} update landed"
    if title:
        body += f": {title}"
    segment = item.get("patient_segment") if isinstance(item, dict) else None
    if segment == "high_risk_adults":
        count = facts.get("high_risk_adult_count") or merchant.customer_aggregate.get("high_risk_adult_count")
        if count:
            body += f". Your roster includes {count} high-risk adult patients"
    if source:
        body += f" ({source})"
    if trigger.kind == "research_digest":
        cta = "Want me to pull the source and draft a patient message?"
    elif plan.cta == "confirm":
        cta = "Should I prepare the compliance checklist?"
    else:
        cta = "Want me to prepare the next step?"
    owner = str(merchant.identity.get("owner_first_name") or "")
    return f"{body}. {cta}", [owner, title or "", source or ""]


def _render_perf_dip(
    sal: str,
    category: CategoryContext,
    trigger: NormalizedTrigger,
    facts: dict[str, Any],
    plan: MessagePlan,
) -> tuple[str, list[str]]:
    performance = facts.get("performance", {})
    metric = performance.get("metric") if isinstance(performance, dict) else None
    delta = performance.get("delta_pct") if isinstance(performance, dict) else None

    # Use peer comparison when available for richer specificity
    peer_sentence = _peer_ctr_sentence(facts)

    if trigger.kind == "seasonal_perf_dip":
        # Reframe: this is expected — don't alarm
        season_note = trigger.facts.get("season_note", "").replace("_", " ")
        if metric and delta is not None:
            body = f"{sal}, your {metric} is down {_percent(delta)} this week"
            if season_note:
                body += f" — this is the normal {season_note} dip"
            if peer_sentence:
                body += f". {peer_sentence.capitalize()}"
            body += ". No action needed on spend — focus on retaining current members."
            return f"{body} Want me to draft a retention nudge?", [sal, metric, _percent(delta)]
        body = f"{sal}, the current {metric or 'performance'} dip is seasonal and expected"
        return f"{body}. Want me to draft a retention message for your active customers?", [sal]

    # Regular perf_dip
    if metric and delta is not None:
        body = f"{sal}, your {metric} is down {_percent(delta)}"
        if peer_sentence:
            body += f". {peer_sentence.capitalize()}"
        return f"{body}. Want me to review the next action?", [sal, metric, _percent(delta)]

    return f"{sal}, there is a performance dip worth reviewing. Want me to prepare options?", [sal]


def _render_perf_spike(
    sal: str,
    category: CategoryContext,
    trigger: NormalizedTrigger,
    facts: dict[str, Any],
) -> tuple[str, list[str]]:
    offer = facts.get("offer")
    offer_title = offer.get("title") if isinstance(offer, dict) else None
    metric = trigger.facts.get("metric")
    delta = trigger.facts.get("delta_pct")
    peer_sentence = _peer_ctr_sentence(facts)

    if metric and delta is not None:
        body = f"{sal}, your {metric} is up {_percent(delta)} this week"
        if peer_sentence:
            body += f". {peer_sentence.capitalize()}"
        if offer_title:
            body += f". Your active offer is {offer_title}"
        return f"{body}. Want me to prepare a promotion to capitalise on this?", [sal, metric, _percent(delta)]

    detail = f" Your active offer is {offer_title}." if offer_title else ""
    if peer_sentence:
        detail = f" {peer_sentence.capitalize()}.{detail}"
    return (
        f"{sal}, demand for {category.slug} is up.{detail} "
        f"Want me to prepare a promotion?",
        [sal, offer_title or ""],
    )


def _render_milestone(sal: str, facts: dict[str, Any]) -> tuple[str, list[str]]:
    metric = facts.get("metric")
    value_now = facts.get("value_now")
    milestone_value = facts.get("milestone_value")
    is_imminent = facts.get("is_imminent")
    gap = facts.get("milestone_gap")

    if is_imminent and milestone_value and value_now is not None:
        if gap is not None and gap > 0:
            remaining = gap
            detail = f"you are at {value_now} {_metric_label(metric)} — just {remaining} away from the {milestone_value} milestone"
        else:
            detail = f"you just crossed {milestone_value} {_metric_label(metric)}"
    elif value_now is not None and metric:
        detail = f"you are at {value_now} {_metric_label(metric)}"
    else:
        detail = "you have hit a new milestone"

    return (
        f"{sal}, {detail}. Want me to draft a milestone post to share with your customers?",
        [sal, str(value_now or ""), str(milestone_value or "")],
    )


def _render_festival_upcoming(sal: str, facts: dict[str, Any]) -> tuple[str, list[str]]:
    festival = facts.get("festival")
    date = facts.get("date")
    days_until = facts.get("days_until") or facts.get("days_until_festival")
    offer = facts.get("offer", {})
    title = offer.get("title") if isinstance(offer, dict) else None

    timing = ""
    if days_until is not None:
        timing = f" in {days_until} days"
    elif date:
        timing = f" on {date}"

    detail = f"{festival}{timing}" if festival else f"an upcoming occasion{timing}"
    offer_note = f" Your active offer, {title}, fits well." if title else ""

    return (
        f"{sal}, {detail} is coming up.{offer_note} "
        f"Want me to prepare one category-fit campaign idea?",
        [sal, str(festival or ""), str(date or "")],
    )


def _render_curious_ask(
    sal: str,
    category: CategoryContext,
    merchant: MerchantContext,
    facts: dict[str, Any],
) -> tuple[str, list[str]]:
    """
    Curious-ask template.  No internal vocabulary.  Uses category trend and
    merchant performance to make the question feel specific and valuable.
    """
    top_query = facts.get("top_trend_query")
    top_delta = facts.get("top_trend_delta_yoy")
    peer_views = facts.get("peer_avg_views") or (
        category.peer_stats.get("avg_views_30d") if category.peer_stats else None
    )
    merchant_views = merchant.performance.get("views")

    # Build a context-specific prompt for the merchant
    if top_query and top_delta is not None:
        trend_pct = f"{abs(top_delta) * 100:g}%"
        body = (
            f"{sal}, searches for '{top_query}' are up {trend_pct} in your category. "
            f"Quick check — which service has been most requested at your place this week?"
        )
        cta = "I will turn your answer into a Google post and a ready-to-share customer note."
        return f"{body} {cta}", [sal, top_query, trend_pct]

    if merchant_views is not None and peer_views is not None:
        body = (
            f"{sal}, your profile had {merchant_views} views this month "
            f"(category average is {peer_views}). "
            f"Quick check — which service has been most requested at your place this week?"
        )
        cta = "I will turn your answer into a Google post."
        return f"{body} {cta}", [sal, str(merchant_views), str(peer_views)]

    # Minimal grounded fallback
    body = (
        f"{sal}, quick check — which service or product has been most asked for "
        f"at your {category.slug} this week?"
    )
    cta = "I will turn your answer into a Google post and a ready-to-use customer reply."
    return f"{body} {cta}", [sal, category.slug]


def _render_winback(
    sal: str,
    category: CategoryContext,
    merchant: MerchantContext,
    facts: dict[str, Any],
) -> tuple[str, list[str]]:
    """
    Winback template.  Uses grounded expiry and performance facts — no fabricated counts.
    """
    days_since_expiry = facts.get("days_since_expiry")
    perf_dip_pct = facts.get("perf_dip_pct")
    lapsed_added = facts.get("lapsed_customers_added_since_expiry")
    peer_ctr_str = _peer_ctr_sentence(facts)

    parts: list[str] = []
    if days_since_expiry is not None:
        parts.append(f"your subscription lapsed {days_since_expiry} days ago")
    if perf_dip_pct is not None:
        parts.append(f"profile performance has dropped {_percent(perf_dip_pct)} since then")
    if lapsed_added is not None:
        parts.append(f"{lapsed_added} additional customers have lapsed in that window")
    if peer_ctr_str:
        parts.append(peer_ctr_str)

    if parts:
        summary = "; ".join(parts[:3])  # cap at 3 facts
        return (
            f"{sal}, {summary}. "
            f"Want me to prepare a plan to get things back on track?",
            [sal, str(days_since_expiry or ""), str(lapsed_added or "")],
        )

    return (
        f"{sal}, there is a good opportunity to reactivate your account now. "
        f"Want me to prepare the next step?",
        [sal],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _salutation(category: CategoryContext, owner: str) -> str:
    if category.slug == "dentists" and owner and not owner.casefold().startswith("dr"):
        return f"Dr. {owner}"
    return owner


def _peer_ctr_sentence(facts: dict[str, Any]) -> str:
    """Return a grounded CTR comparison sentence, or '' if data is missing."""
    merchant_ctr = facts.get("merchant_ctr") or facts.get("current_ctr")
    peer_ctr = facts.get("peer_avg_ctr")
    if merchant_ctr is not None and peer_ctr is not None:
        return (
            f"your CTR is {_pct(merchant_ctr)}, "
            f"vs the {_pct(peer_ctr)} category peer median"
        )
    return ""


def _pct(value: float) -> str:
    return f"{value * 100:g}%"


def _metric_label(metric: str | None) -> str:
    if not metric:
        return ""
    return metric.replace("_", " ")


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
