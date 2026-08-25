"""Generate grounded candidate actions before scoring and message rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import CategoryContext, CustomerContext, MerchantContext
from .signals import NormalizedTrigger, Signal


@dataclass(frozen=True)
class CandidateAction:
    objective: str
    action_type: str
    cta: str
    primary_signal: str
    evidence: tuple[str, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)
    priority_hint: int = 0
    trigger_evidence: tuple[str, ...] = ()
    merchant_evidence: tuple[str, ...] = ()
    category_evidence: tuple[str, ...] = ()
    customer_evidence: tuple[str, ...] = ()
    offer_evidence: tuple[str, ...] = ()
    conversation_evidence: tuple[str, ...] = ()


def _active_offer(merchant: MerchantContext) -> dict[str, Any] | None:
    for offer in merchant.offers:
        if str(offer.get("status", "")).lower() == "active" and offer.get("title"):
            return offer
    return None


def _has_consent(customer: CustomerContext) -> bool:
    if customer.preferences.get("reminder_opt_in") is False:
        return False
    return bool(customer.consent.get("opted_in_at")) and bool(customer.consent.get("scope"))


def generate_candidates(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    signals: list[Signal],
    customer: CustomerContext | None = None,
) -> list[CandidateAction]:
    """Build stable candidates using only facts available to the caller."""
    by_name = {signal.name: signal for signal in signals}
    candidates: list[CandidateAction] = []
    offer = _active_offer(merchant)

    if trigger.scope == "customer":
        if not customer or customer.customer_id != trigger.customer_id or not _has_consent(customer):
            return []
        if trigger.kind in {"recall_due", "chronic_refill_due", "appointment_tomorrow", "trial_followup"}:
            facts = {signal.name: signal.value for signal in signals if signal.name.startswith("customer_")}
            facts.update(trigger.facts)
            if offer:
                facts["offer"] = offer
            candidates.append(CandidateAction(
                objective="customer_follow_up",
                action_type="customer_outreach",
                cta="confirm",
                primary_signal="customer_followup",
                evidence=tuple(evidence for signal in signals for evidence in signal.evidence),
                facts={"customer_name": customer.identity.get("name", ""), "customer_state": customer.state, **facts},
                priority_hint=90,
                merchant_evidence=(str(offer.get("title")),) if offer else (),
                customer_evidence=(customer.state, str(customer.preferences.get("preferred_slots", ""))),
                offer_evidence=(str(offer.get("title")),) if offer else (),
            ))
        elif trigger.kind in {"customer_lapsed_soft", "customer_lapsed_hard"} and "customer_lapse" in by_name:
            candidates.append(CandidateAction(
                objective="reactivate_customer",
                action_type="customer_outreach",
                cta="book",
                primary_signal="customer_lapse",
                evidence=by_name["customer_lapse"].evidence,
                facts={"customer_name": customer.identity.get("name", ""), "state": customer.state, **trigger.facts, **({"offer": offer} if offer else {})},
                priority_hint=80,
                customer_evidence=(customer.state, str(customer.preferences.get("preferred_slots", ""))),
                offer_evidence=(str(offer.get("title")),) if offer else (),
            ))
        return candidates

    if trigger.kind in {"research_digest", "cde_opportunity"} and "category_digest_item" in by_name:
        item = by_name["category_digest_item"].value
        merchant_evidence = tuple(str(signal) for signal in merchant.signals if signal)
        category_evidence = tuple(
            str(item.get(key)) for key in ("patient_segment", "actionable") if item.get(key)
        )
        conversation_evidence = tuple(
            str(turn.get("body")) for turn in merchant.conversation_history[-2:] if turn.get("body")
        )
        facts = {"digest_item": item}
        if merchant.customer_aggregate.get("high_risk_adult_count") and item.get("patient_segment") == "high_risk_adults":
            facts["high_risk_adult_count"] = merchant.customer_aggregate["high_risk_adult_count"]
        if offer:
            facts["offer"] = offer
        candidates.append(CandidateAction(
            objective="share_relevant_category_knowledge",
            action_type="inform",
            cta="view",
            primary_signal="category_digest_item",
            evidence=by_name["category_digest_item"].evidence,
            facts=facts,
            priority_hint=85 if merchant_evidence or conversation_evidence else 70,
            trigger_evidence=by_name["category_digest_item"].evidence,
            merchant_evidence=merchant_evidence,
            category_evidence=category_evidence,
            offer_evidence=(str(offer.get("title")),) if offer else (),
            conversation_evidence=conversation_evidence,
        ))

    if trigger.kind == "regulation_change" and "category_digest_item" in by_name:
        candidates.append(CandidateAction(
            objective="surface_compliance_change",
            action_type="recommend",
            cta="confirm",
            primary_signal="category_digest_item",
            evidence=by_name["category_digest_item"].evidence,
            facts={"digest_item": by_name["category_digest_item"].value, "deadline": trigger.facts.get("deadline_iso", "")},
            priority_hint=95,
            trigger_evidence=by_name["category_digest_item"].evidence,
            category_evidence=(str(trigger.facts.get("deadline_iso")),) if trigger.facts.get("deadline_iso") else (),
        ))

    if trigger.kind in {"perf_dip", "seasonal_perf_dip"} and "performance_decline" in by_name:
        action_type = "inform" if "expected_seasonal_decline" in by_name else "recommend"
        candidates.append(CandidateAction(
            objective="reframe_performance_decline" if action_type == "inform" else "address_performance_decline",
            action_type=action_type,
            cta="view" if action_type == "inform" else "approve",
            primary_signal="performance_decline",
            evidence=by_name["performance_decline"].evidence,
            facts={"performance": by_name["performance_decline"].value},
            priority_hint=65 if action_type == "inform" else 75,
        ))

    if trigger.kind in {"perf_spike", "category_seasonal"}:
        signal_name = "performance_increase" if "performance_increase" in by_name else "seasonal_demand_shift"
        if signal_name in by_name:
            candidates.append(CandidateAction(
                objective="capitalize_on_demand",
                action_type="recommend" if offer else "inform",
                cta="promote" if offer else "view",
                primary_signal=signal_name,
                evidence=by_name[signal_name].evidence,
                facts={signal_name: by_name[signal_name].value, "offer": offer} if offer else {signal_name: by_name[signal_name].value},
                priority_hint=75 if offer else 50,
            ))

    if trigger.kind in {"supply_alert", "review_theme_emerged", "competitor_opened", "gbp_unverified", "renewal_due", "milestone_reached", "dormant_with_vera", "festival_upcoming", "active_planning_intent", "curious_ask_due", "winback_eligible"}:
        useful_facts = dict(trigger.facts)
        if offer:
            useful_facts["offer"] = offer
        if useful_facts or merchant.signals:
            candidates.append(CandidateAction(
                objective=_objective_for_kind(trigger.kind),
                action_type="recommend",
                cta=_cta_for_kind(trigger.kind),
                primary_signal=f"trigger:{trigger.kind}",
                evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
                facts=useful_facts,
                priority_hint=max(40, trigger.urgency * 15),
            ))

    if not candidates and (trigger.facts or merchant.signals):
        fallback_facts = dict(trigger.facts)
        if offer:
            fallback_facts["offer"] = offer
        candidates.append(CandidateAction(
            objective="review_current_signal",
            action_type="inform",
            cta="reply",
            primary_signal=f"trigger:{trigger.kind or 'unknown'}",
            evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
            facts=fallback_facts,
            priority_hint=max(10, trigger.urgency * 10),
        ))

    return candidates


def _objective_for_kind(kind: str) -> str:
    return {
        "supply_alert": "address_supply_alert",
        "review_theme_emerged": "address_review_theme",
        "competitor_opened": "respond_to_competitor_change",
        "gbp_unverified": "complete_business_profile",
        "renewal_due": "renew_subscription",
        "milestone_reached": "amplify_milestone",
        "dormant_with_vera": "restart_merchant_conversation",
        "festival_upcoming": "prepare_seasonal_campaign",
        "active_planning_intent": "continue_active_plan",
        "curious_ask_due": "ask_merchant_for_insight",
        "winback_eligible": "propose_merchant_winback",
    }.get(kind, "review_current_signal")


def _cta_for_kind(kind: str) -> str:
    return {
        "supply_alert": "approve",
        "review_theme_emerged": "view",
        "competitor_opened": "view",
        "gbp_unverified": "confirm",
        "renewal_due": "confirm",
        "milestone_reached": "approve",
        "dormant_with_vera": "reply",
        "festival_upcoming": "approve",
        "active_planning_intent": "send",
        "curious_ask_due": "reply",
        "winback_eligible": "approve",
    }.get(kind, "reply")