"""Suppression filtering and deterministic action selection."""

from __future__ import annotations

from dataclasses import dataclass

from .candidates import CandidateAction
from .models import CustomerContext, MerchantContext
from .scoring import ScoredCandidate
from .store import ConversationStore, SuppressionStore


@dataclass(frozen=True)
class SelectionResult:
    selected: ScoredCandidate | None
    reason: str = ""


def select_candidate(
    ranked: list[ScoredCandidate],
    merchant: MerchantContext,
    suppression_store: SuppressionStore,
    conversation_store: ConversationStore,
    conversation_id: str,
    customer: CustomerContext | None = None,
) -> SelectionResult:
    """Select the first eligible ranked candidate and record its state."""
    if not ranked:
        return SelectionResult(None, "no_candidates")

    if customer and not _customer_is_contactable(customer):
        return SelectionResult(None, "customer_not_contactable")

    if suppression_store.conversation_suppressed(conversation_id):
        return SelectionResult(None, "conversation_suppressed")

    state = conversation_store.get_or_create(
        conversation_id,
        merchant.merchant_id,
        customer.customer_id if customer else None,
    )
    for scored in ranked:
        candidate = scored.candidate
        key = _candidate_key(candidate)
        if key and suppression_store.contains(key):
            continue
        if candidate.action_type == "customer_outreach" and not customer:
            continue
        if candidate.cta and candidate.cta in {"approve", "promote", "send"} and _same_objective_sent(state, candidate):
            continue
        suppression_store.add(key)
        state.suppression_keys.add(key)
        return SelectionResult(scored, "selected")

    return SelectionResult(None, "all_candidates_suppressed")


def select_tick_actions(
    ranked_by_trigger: list[tuple[str, list[ScoredCandidate]]],
    merchant_by_trigger: dict[str, MerchantContext],
    suppression_store: SuppressionStore,
    conversation_store: ConversationStore,
    customer_by_trigger: dict[str, CustomerContext | None] | None = None,
    limit: int = 20,
) -> list[tuple[str, SelectionResult]]:
    """Select at most one action per trigger and at most ``limit`` actions."""
    selected: list[tuple[str, SelectionResult]] = []
    customer_by_trigger = customer_by_trigger or {}
    for trigger_id, ranked in ranked_by_trigger:
        if len(selected) >= max(0, limit):
            break
        merchant = merchant_by_trigger.get(trigger_id)
        if not merchant:
            continue
        customer = customer_by_trigger.get(trigger_id)
        conversation_id = f"conv_{merchant.merchant_id}_{trigger_id}"
        result = select_candidate(
            ranked,
            merchant,
            suppression_store,
            conversation_store,
            conversation_id,
            customer,
        )
        if result.selected:
            selected.append((trigger_id, result))
    return selected


def _candidate_key(candidate: CandidateAction) -> str:
    key = candidate.facts.get("suppression_key")
    if isinstance(key, str) and key:
        return key
    return f"candidate:{candidate.objective}:{candidate.primary_signal}"


def _same_objective_sent(state, candidate: CandidateAction) -> bool:
    return any(
        turn.get("candidate_objective") == candidate.objective
        for turn in state.turns
        if isinstance(turn, dict)
    )


def _customer_is_contactable(customer: CustomerContext) -> bool:
    if customer.preferences.get("reminder_opt_in") is False:
        return False
    consent_scope = customer.consent.get("scope")
    return bool(customer.consent.get("opted_in_at") and isinstance(consent_scope, list) and consent_scope)