"""Generate grounded candidate actions before scoring and message rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import CategoryContext, CustomerContext, MerchantContext
from .signals import NormalizedTrigger, Signal


# ---------------------------------------------------------------------------
# Festival proximity and relevance helpers
# ---------------------------------------------------------------------------

# Configurable proximity bands: (max_days_exclusive, factor)
# Processed in order — first matching band wins.
FESTIVAL_PROXIMITY_BANDS: tuple[tuple[int, float], ...] = (
    (14,  1.0),   # 0–13 days:   immediate activation
    (60,  0.9),   # 14–59 days:  strong preparation window
    (120, 0.6),   # 60–119 days: planning window
    # > 120 days: very weak urgency (default below)
)
FESTIVAL_PROXIMITY_DEFAULT: float = 0.3  # > 120 days


def _festival_proximity_factor(days_until: int | None) -> float:
    """Return a 0.0–1.0 multiplier based on how far away the festival is.

    Proximity is a *ranking* feature, not a suppression gate.  A distant
    festival with strong merchant evidence can still produce a useful action;
    the factor simply ensures it competes fairly against nearer opportunities.
    """
    if days_until is None or days_until < 0:
        return FESTIVAL_PROXIMITY_DEFAULT
    for max_days, factor in FESTIVAL_PROXIMITY_BANDS:
        if days_until < max_days:
            return factor
    return FESTIVAL_PROXIMITY_DEFAULT


# Keywords that indicate a festival-relevant offer or service.
# Checked case-insensitively against offer title.
_FESTIVAL_OFFER_KEYWORDS: frozenset[str] = frozenset({
    "bridal", "bride", "wedding", "festive", "festival", "diwali", "holi",
    "eid", "navratri", "puja", "mehendi", "occasion", "special",
    "party", "celebration", "anniversary", "gala",
})

# Keywords in seasonal beat notes that indicate the beat is festival-relevant.
_FESTIVAL_BEAT_KEYWORDS: frozenset[str] = frozenset({
    "wedding", "festival", "bridal", "festive", "diwali", "navratri",
    "eid", "holi", "celebration", "season",
})


def _festival_offer_relevance(
    offer: dict[str, Any] | None,
    festival_name: str | None,
    category: CategoryContext,
    days_until: int | None,
) -> float:
    """Return a 0.0–1.0 offer-relevance score for a festival campaign.

    Rules (in priority order):
    1. If days_until <= 60 (near-term): any active offer is acceptable (1.0).
       The offer is relevant because the planning window is tight.
    2. If the offer title contains festival-relevant keywords: 1.0.
    3. If a category seasonal beat covers the festival month and references
       relevant services: 0.8.
    4. If the festival name appears in category_relevance but no offer match: 0.5.
    5. Otherwise: 0.2 (low relevance — generic offer, distant festival).
    """
    if days_until is not None and days_until <= 60:
        return 1.0

    offer_title = str(offer.get("title", "")).casefold() if offer else ""
    if any(kw in offer_title for kw in _FESTIVAL_OFFER_KEYWORDS):
        return 1.0

    # Check if any seasonal beat note is relevant to the festival month
    festival_lower = (festival_name or "").casefold()
    for beat in category.seasonal_beats:
        note = str(beat.get("note", "")).casefold()
        if any(kw in note for kw in _FESTIVAL_BEAT_KEYWORDS):
            return 0.8

    return 0.2


def _has_festival_planning_intent(
    merchant: MerchantContext,
    festival_name: str | None,
) -> bool:
    """Return True if the merchant (not Vera) has expressed planning intent
    for this festival or bridal/festive services in the conversation history."""
    festival_lower = (festival_name or "").casefold()
    keywords = {festival_lower, "bridal", "festive", "wedding", "campaign", "plan", "season"}
    for turn in merchant.conversation_history:
        # Only count merchant-sent turns as planning intent evidence.
        # Vera-sent messages in conversation history are outbound nudges, not
        # evidence that the merchant has expressed intent.
        if str(turn.get("from", "")).casefold() == "vera":
            continue
        body = str(turn.get("body", "")).casefold()
        if any(kw in body for kw in keywords):
            return True
    return False


def _current_seasonal_digest_item(category: CategoryContext) -> dict[str, Any] | None:
    """Return the most actionable current seasonal/trend digest item.

    Preference order: 'seasonal' kind first, then 'trend'.
    """
    seasonal = next((item for item in category.digest if item.get("kind") == "seasonal"), None)
    if seasonal:
        return seasonal
    return next((item for item in category.digest if item.get("kind") == "trend"), None)


def _peer_facts(category: CategoryContext, merchant: MerchantContext, metric: str | None = None) -> dict[str, Any]:
    """Return a dict of peer comparison facts grounded in both category and merchant data.

    Only populates a key when BOTH the merchant value and the peer value exist.
    Never invents numbers.
    """
    peer = category.peer_stats
    if not peer:
        return {}
    facts: dict[str, Any] = {}

    merchant_ctr = merchant.performance.get("ctr")
    peer_ctr = peer.get("avg_ctr")
    if merchant_ctr is not None and peer_ctr is not None:
        facts["merchant_ctr"] = merchant_ctr
        facts["peer_avg_ctr"] = peer_ctr

    if metric and metric != "ctr":
        peer_key = f"avg_{metric}_30d"
        merchant_val = merchant.performance.get(metric)
        peer_val = peer.get(peer_key)
        if merchant_val is not None and peer_val is not None:
            facts[f"merchant_{metric}"] = merchant_val
            facts[f"peer_avg_{metric}"] = peer_val

    avg_views = peer.get("avg_views_30d")
    merchant_views = merchant.performance.get("views")
    if avg_views is not None and merchant_views is not None:
        facts["merchant_views"] = merchant_views
        facts["peer_avg_views"] = avg_views

    return facts


def _performance_actuals(merchant: MerchantContext, metric: str | None = None) -> dict[str, Any]:
    """Return relevant performance actuals for the given metric (or CTR/views as defaults)."""
    perf = merchant.performance
    if not perf:
        return {}
    facts: dict[str, Any] = {}
    if metric:
        val = perf.get(metric)
        if val is not None:
            facts[f"current_{metric}"] = val
        delta_7d = perf.get("delta_7d", {})
        delta = delta_7d.get(f"{metric}_pct")
        if delta is not None:
            facts[f"delta_7d_{metric}_pct"] = delta
    # Always include CTR if present
    ctr = perf.get("ctr")
    if ctr is not None:
        facts["current_ctr"] = ctr
    return facts


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
    merchant_signals = {str(value).casefold() for value in merchant.signals}
    recent_history = tuple(
        str(turn.get("body")) for turn in merchant.conversation_history[-2:] if turn.get("body")
    )

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
                trigger_evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
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
                trigger_evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
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
        metric = trigger.facts.get("metric")
        perf_base_facts: dict[str, Any] = {"performance": by_name["performance_decline"].value}
        perf_base_facts.update(_peer_facts(category, merchant, metric))
        perf_base_facts.update(_performance_actuals(merchant, metric))
        if offer:
            perf_base_facts["offer"] = offer
        candidates.append(CandidateAction(
            objective="reframe_performance_decline" if action_type == "inform" else "address_performance_decline",
            action_type=action_type,
            cta="view" if action_type == "inform" else "approve",
            primary_signal="performance_decline",
            evidence=by_name["performance_decline"].evidence,
            facts=perf_base_facts,
            priority_hint=65 if action_type == "inform" else 75,
            trigger_evidence=by_name["performance_decline"].evidence,
            merchant_evidence=tuple(merchant.signals),
            offer_evidence=(str(offer.get("title")),) if offer else (),
        ))
        if "stale_posts" in " ".join(merchant_signals) or "unverified_gbp" in " ".join(merchant_signals):
            listing_facts: dict[str, Any] = {"performance": by_name["performance_decline"].value, "listing_signals": list(merchant.signals)}
            listing_facts.update(_peer_facts(category, merchant, metric))
            candidates.append(CandidateAction(
                objective="improve_listing",
                action_type="recommend",
                cta="draft",
                primary_signal="performance_decline",
                evidence=by_name["performance_decline"].evidence,
                facts=listing_facts,
                priority_hint=82,
                trigger_evidence=by_name["performance_decline"].evidence,
                merchant_evidence=tuple(merchant.signals),
            ))
        if merchant.customer_aggregate.get("lapsed_180d_plus") and offer:
            candidates.append(CandidateAction(
                objective="reactivate_customers",
                action_type="recommend",
                cta="send",
                primary_signal="performance_decline",
                evidence=by_name["performance_decline"].evidence,
                facts={"performance": by_name["performance_decline"].value, "lapsed_customers": merchant.customer_aggregate["lapsed_180d_plus"], "offer": offer},
                priority_hint=84,
                trigger_evidence=by_name["performance_decline"].evidence,
                merchant_evidence=(f"lapsed_customers={merchant.customer_aggregate['lapsed_180d_plus']}",),
                offer_evidence=(str(offer.get("title")),),
            ))

    if trigger.kind in {"perf_spike", "category_seasonal"}:
        signal_name = "performance_increase" if "performance_increase" in by_name else "seasonal_demand_shift"
        if signal_name in by_name:
            metric = trigger.facts.get("metric")
            spike_facts: dict[str, Any] = {signal_name: by_name[signal_name].value}
            spike_facts.update(_peer_facts(category, merchant, metric))
            spike_facts.update(_performance_actuals(merchant, metric))
            if offer:
                spike_facts["offer"] = offer

            # Fix 2: thread likely_driver as natural language (preserve uncertainty)
            raw_driver = trigger.facts.get("likely_driver")
            if raw_driver:
                spike_facts["spike_driver_label"] = _translate_likely_driver(raw_driver)

            # Fix 2: thread relevant conversation context (last merchant-sent turn)
            for turn in reversed(merchant.conversation_history):
                if str(turn.get("from", "")).casefold() != "vera":
                    spike_facts["relevant_conversation"] = str(turn.get("body", ""))[:120]
                    break

            # Fix 3: surface the current seasonal strategy from category beats
            strategy = _seasonal_strategy(category)
            spike_facts["seasonal_strategy"] = strategy

            # Fix 3: thread the matching seasonal beat note when strategy is non-acquisition
            if strategy != "acquisition":
                for beat in category.seasonal_beats:
                    note = str(beat.get("note", "")).casefold()
                    if any(kw in note for kw in ("retention", "lowest", "focus on")):
                        spike_facts["seasonal_beat_note"] = beat.get("note", "")
                        break

            # CTA: retention season → 'send' (follow-up draft); acquisition/neutral → 'promote'
            spike_cta = "send" if strategy == "retention" else ("promote" if offer else "view")

            candidates.append(CandidateAction(
                objective="capitalize_on_demand",
                action_type="recommend" if offer else "inform",
                cta=spike_cta,
                primary_signal=signal_name,
                evidence=by_name[signal_name].evidence,
                facts=spike_facts,
                priority_hint=75 if offer else 50,
                trigger_evidence=by_name[signal_name].evidence,
                merchant_evidence=tuple(merchant.signals),
                offer_evidence=(str(offer.get("title")),) if offer else (),
                conversation_evidence=recent_history,
            ))

    if trigger.kind in {"supply_alert", "review_theme_emerged", "competitor_opened", "gbp_unverified", "renewal_due", "milestone_reached", "dormant_with_vera", "festival_upcoming", "active_planning_intent", "curious_ask_due", "winback_eligible"}:
        useful_facts = dict(trigger.facts)
        if offer:
            useful_facts["offer"] = offer
        # Thread peer stats and performance actuals for opportunity triggers
        useful_facts.update(_peer_facts(category, merchant))
        useful_facts.update(_performance_actuals(merchant))
        if useful_facts or merchant.signals:
            candidates.append(CandidateAction(
                objective=_objective_for_kind(trigger.kind),
                action_type="recommend",
                cta=_cta_for_kind(trigger.kind),
                primary_signal=f"trigger:{trigger.kind}",
                evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
                facts=useful_facts,
                priority_hint=max(40, trigger.urgency * 15),
                trigger_evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
                merchant_evidence=tuple(merchant.signals),
                offer_evidence=(str(offer.get("title")),) if offer else (),
                conversation_evidence=recent_history,
            ))

    if trigger.kind == "dormant_with_vera":
        days = trigger.facts.get("days_since_last_merchant_message")
        if days is not None and (offer or merchant.signals):
            dormant_facts: dict[str, Any] = {"days_inactive": days}
            if offer:
                dormant_facts["offer"] = offer
            dormant_facts.update(_peer_facts(category, merchant))
            dormant_facts.update(_performance_actuals(merchant))
            candidates.append(CandidateAction(
                objective="restart_merchant_conversation",
                action_type="recommend",
                cta="reply",
                primary_signal="trigger:dormant_with_vera",
                evidence=("trigger.payload.days_since_last_merchant_message",),
                facts=dormant_facts,
                priority_hint=70,
                trigger_evidence=("trigger.payload.days_since_last_merchant_message",),
                merchant_evidence=tuple(merchant.signals),
                offer_evidence=(str(offer.get("title")),) if offer else (),
                conversation_evidence=recent_history,
            ))

    if trigger.kind == "festival_upcoming" and offer:
        days_until = trigger.facts.get("days_until")
        festival_name = trigger.facts.get("festival")
        has_planning_intent = _has_festival_planning_intent(merchant, festival_name)
        proximity = _festival_proximity_factor(days_until)
        offer_relevance = _festival_offer_relevance(offer, festival_name, category, days_until)

        # Base priority before proximity adjustment
        base_priority = 78
        # Planning intent or near-term event overrides the proximity penalty
        if has_planning_intent:
            proximity = max(proximity, 0.9)
        # Effective priority = base × proximity × offer_relevance
        # Clamp to int in range [15, 78]
        effective_priority = max(15, min(base_priority, int(base_priority * proximity * offer_relevance + 0.5)))

        festival_facts: dict[str, Any] = {
            "festival": festival_name,
            "date": trigger.facts.get("date"),
            "days_until": days_until,
            "category_relevance": trigger.facts.get("category_relevance"),
            "offer": offer,
            # Pass proximity metadata so the template can frame the message honestly
            "proximity_factor": proximity,
            "offer_relevance": offer_relevance,
            "has_planning_intent": has_planning_intent,
        }
        # Carry seasonal beat note when available, to give the template a grounded
        # reason why this festival matters to this category.
        relevant_beat = next(
            (b for b in category.seasonal_beats if any(
                kw in str(b.get("note", "")).casefold()
                for kw in _FESTIVAL_BEAT_KEYWORDS
            )),
            None,
        )
        if relevant_beat:
            festival_facts["seasonal_beat_note"] = relevant_beat.get("note", "")
            festival_facts["seasonal_beat_months"] = relevant_beat.get("month_range", "")

        candidates.append(CandidateAction(
            objective="plan_seasonal_campaign",
            action_type="recommend",
            cta="draft",
            primary_signal="trigger:festival_upcoming",
            evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
            facts=festival_facts,
            priority_hint=effective_priority,
            trigger_evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
            merchant_evidence=tuple(merchant.signals),
            offer_evidence=(str(offer.get("title")),),
        ))

        # Opportunity competition: when the festival is distant and a stronger
        # current demand signal exists in the category digest, generate a
        # competing candidate for the immediate opportunity.
        # This respects the challenge contract — we only use what is in the
        # pushed context, not invented triggers.
        if days_until is not None and days_until > 60 and not has_planning_intent:
            current_item = _current_seasonal_digest_item(category)
            if current_item:
                item_title = current_item.get("title", "")
                item_source = current_item.get("source", "")
                item_actionable = current_item.get("actionable", "")
                digest_facts: dict[str, Any] = {
                    "digest_item": current_item,
                    "seasonal_beat_note": item_title,
                }
                if offer:
                    digest_facts["offer"] = offer
                # Evidence from conversation history (unanswered bridal ask etc.)
                recent_conv = tuple(
                    str(t.get("body")) for t in merchant.conversation_history[-2:] if t.get("body")
                )
                candidates.append(CandidateAction(
                    objective="share_relevant_category_knowledge",
                    action_type="inform",
                    cta="view",
                    primary_signal="category_seasonal_opportunity",
                    evidence=(f"category.digest.id={current_item.get('id', '')}",),
                    facts=digest_facts,
                    # Priority reflects urgency of the *current* seasonal window
                    priority_hint=72,
                    trigger_evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
                    merchant_evidence=tuple(merchant.signals),
                    category_evidence=(item_title, item_actionable) if item_actionable else (item_title,),
                    offer_evidence=(str(offer.get("title")),) if offer else (),
                    conversation_evidence=recent_conv,
                ))

    if trigger.kind in {"active_planning_intent", "curious_ask_due"} and recent_history:
        # Surface intent_topic and merchant_last_message as top-level keys so
        # the template can read them directly without dict nesting.
        intent_facts: dict[str, Any] = {
            "intent": trigger.facts,
            "recent_message": recent_history[-1],
        }
        if trigger.facts.get("intent_topic"):
            intent_facts["intent_topic"] = trigger.facts["intent_topic"]
        merchant_last = trigger.facts.get("merchant_last_message")
        if merchant_last:
            intent_facts["merchant_last_message"] = merchant_last
            # Fix 1: detect confirmed intent — if the merchant already said yes,
            # flag it so the template produces an artifact, not another question.
            intent_facts["merchant_confirms"] = _is_confirmed_intent(merchant_last)

        # Fix 1: thread grounded artifact skeleton when intent is confirmed
        if intent_facts.get("merchant_confirms"):
            skeleton = _grounded_artifact_skeleton(
                trigger.facts.get("intent_topic", ""),
                merchant,
                offer,
            )
            if skeleton:
                intent_facts["artifact_skeleton"] = skeleton

        candidates.append(CandidateAction(
            objective="prepare_content",
            action_type="recommend",
            cta="draft",
            primary_signal=f"trigger:{trigger.kind}",
            evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
            facts=intent_facts,
            priority_hint=86 if trigger.kind == "active_planning_intent" else 68,
            trigger_evidence=tuple(f"trigger.payload.{key}" for key in sorted(trigger.facts)),
            merchant_evidence=tuple(merchant.signals),
            conversation_evidence=recent_history,
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
        "milestone_reached": "send",
        "dormant_with_vera": "reply",
        "festival_upcoming": "approve",
        "active_planning_intent": "send",
        "curious_ask_due": "reply",
        "winback_eligible": "approve",
    }.get(kind, "reply")


# ---------------------------------------------------------------------------
# Fix 1 helpers — confirmed planning intent
# ---------------------------------------------------------------------------

_CONFIRMATION_MARKERS: frozenset[str] = frozenset({
    "yes", "yes good", "yes good idea", "good idea", "go ahead",
    "let's do it", "lets do it", "sounds good", "great idea",
    "proceed", "please proceed", "ok let's", "ok lets", "sure",
    "do it", "perfect", "makes sense", "agreed",
})


def _is_confirmed_intent(merchant_last_message: str) -> bool:
    """Return True when the merchant's last message is an explicit confirmation.

    Conservative — only marks as confirmed when the evidence is unambiguous,
    to avoid producing a premature artifact for ambiguous replies.
    """
    if not merchant_last_message:
        return False
    text = " ".join(merchant_last_message.casefold().split())
    if text in _CONFIRMATION_MARKERS:
        return True
    for marker in _CONFIRMATION_MARKERS:
        if text.startswith(marker):
            return True
    return False


def _grounded_artifact_skeleton(
    intent_topic: str,
    merchant: MerchantContext,
    offer: "dict[str, Any] | None",
) -> str:
    """Return a grounded artifact skeleton using only facts from the context.

    Uses active offer titles already present in MerchantContext.offers.
    Never invents prices, delivery times, or capabilities.
    Returns '' when no useful skeleton can be grounded.
    """
    topic = (intent_topic or "").casefold().replace("_", " ")
    active_offers = [
        o for o in merchant.offers
        if str(o.get("status", "")).casefold() == "active" and o.get("title")
    ]

    if any(kw in topic for kw in ("corporate", "bulk", "office", "enterprise", "group")):
        if active_offers:
            base = active_offers[0]["title"]
            return (
                f"Corporate lunch package — draft structure:\n"
                f"- Base unit: {base}\n"
                f"- Bulk-order pricing: to be confirmed\n"
                f"- Minimum order: to be confirmed\n"
                f"- Delivery window: to be confirmed\n"
                f"- How to order: WhatsApp the day before"
            )
        return ""

    if any(kw in topic for kw in ("bridal", "wedding", "bride")):
        if active_offers:
            base = active_offers[0]["title"]
            return (
                f"Bridal package — draft structure:\n"
                f"- Base service: {base}\n"
                f"- Add-on options: to be confirmed from your menu\n"
                f"- Trial session: to be confirmed\n"
                f"- Booking lead time: to be confirmed"
            )
        return ""

    # Generic planning artifact
    if active_offers:
        base = active_offers[0]["title"]
        return (
            f"Draft structure — starting point: {base}\n"
            f"- Pricing: to be confirmed\n"
            f"- Availability: to be confirmed\n"
            f"- Logistics: to be confirmed"
        )
    return ""


# ---------------------------------------------------------------------------
# Fix 2 / 3 helpers — perf_spike driver translation + seasonal strategy
# ---------------------------------------------------------------------------

_DRIVER_LABELS: dict[str, str] = {
    "kids_yoga_post": "your recent kids-yoga post",
    "kids_yoga": "the kids-yoga content",
    "ipl_post": "your IPL promotion post",
    "festival_post": "your recent festival post",
    "gbp_update": "your recent Google Business Profile update",
    "offer_post": "your active offer post",
    "instagram_post": "a recent Instagram post",
    "google_post": "a recent Google post",
    "walk_in_tag": "the walk-in availability tag on your profile",
    "bridal_post": "your bridal content",
    "referral": "word-of-mouth referrals",
    "organic": "organic search growth",
}


def _translate_likely_driver(raw: str) -> str:
    """Translate a raw likely_driver value to a natural merchant-facing phrase.

    Preserves the 'likely' uncertainty — never says 'caused by'.
    Returns '' when no translation is available.
    """
    key = (raw or "").casefold().replace("-", "_").replace(" ", "_")
    label = _DRIVER_LABELS.get(key)
    if label:
        return label
    if "_" in key or key.isalpha():
        return raw.replace("_", " ").replace("-", " ")
    return ""


_RETENTION_SEASON_KEYWORDS: frozenset[str] = frozenset({
    "retention", "lowest acquisition", "focus on retention",
    "not acquisition", "churn", "slowdown", "lowest",
})

_ACQUISITION_SEASON_KEYWORDS: frozenset[str] = frozenset({
    "acquisition", "walk-in", "trial", "surge", "peak", "convert window",
    "new member", "new client", "onboarding",
})


def _seasonal_strategy(category: CategoryContext) -> str:
    """Return 'retention', 'acquisition', or 'neutral' based on category seasonal beats.

    Uses keyword scan — does NOT hard-code months.  Returns 'neutral' when
    the beats are ambiguous or absent.
    """
    for beat in category.seasonal_beats:
        note = str(beat.get("note", "")).casefold()
        if any(kw in note for kw in _RETENTION_SEASON_KEYWORDS):
            return "retention"
    for beat in category.seasonal_beats:
        note = str(beat.get("note", "")).casefold()
        if any(kw in note for kw in _ACQUISITION_SEASON_KEYWORDS):
            return "acquisition"
    return "neutral"
