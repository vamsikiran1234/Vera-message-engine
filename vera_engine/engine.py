"""Orchestrate the deterministic Vera decision pipeline for tick requests."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .candidates import generate_candidates
from .models import CategoryContext, ComposedAction, CustomerContext, MerchantContext, TriggerContext
from .observability import DecisionEvent, DecisionLogger, DecisionTimer
from .planner import build_message_plan
from .scoring import rank_candidates
from .selection import select_candidate
from .signals import extract_signals, normalize_trigger
from .store import ContextStore, ConversationStore, SuppressionStore
from .templates import render_message
from .validator import validate_message


class DecisionEngine:
    def __init__(self, contexts: ContextStore, conversations: ConversationStore, suppression: SuppressionStore, logger: DecisionLogger | None = None) -> None:
        self.contexts = contexts
        self.conversations = conversations
        self.suppression = suppression
        self.logger = logger

    def compose_trigger(self, trigger_id: str) -> ComposedAction | None:
        timer = DecisionTimer()
        timer.__enter__()
        trigger_payload = self.contexts.payload("trigger", trigger_id)
        if not trigger_payload:
            self._log(trigger_id, None, None, (), None, None, "missing_trigger", timer)
            return None
        trigger = TriggerContext.from_payload(trigger_payload)
        merchant_payload = self.contexts.payload("merchant", trigger.merchant_id)
        if not merchant_payload:
            self._log(trigger_id, trigger.merchant_id, trigger.customer_id, (), None, None, "missing_merchant", timer)
            return None
        merchant = MerchantContext.from_payload(merchant_payload)
        category_payload = self.contexts.payload("category", merchant.category_slug) or {"slug": merchant.category_slug}
        category = CategoryContext.from_payload(category_payload)
        customer = self._customer(trigger)
        normalized = normalize_trigger(trigger)
        signals = extract_signals(category, merchant, normalized, customer)
        candidates = generate_candidates(category, merchant, normalized, signals, customer)
        ranked = rank_candidates(category, merchant, normalized, candidates, signals, customer)
        if not ranked:
            self._log(trigger_id, merchant.merchant_id, trigger.customer_id, (), None, None, "no_candidates", timer)
            return None

        top = ranked[0].candidate
        if normalized.suppression_key:
            top.facts.setdefault("suppression_key", normalized.suppression_key)
        plan = build_message_plan(category, merchant, normalized, top, customer)
        body, params = render_message(category, merchant, normalized, plan, customer)
        validation = validate_message(body, plan.cta, category, merchant, plan, customer)
        if not validation.valid:
            self._log(trigger_id, merchant.merchant_id, trigger.customer_id, _score_data(ranked), top.primary_signal, top.objective, "validation_failed", timer, plan.suppression_key, validation.valid, validation.reasons)
            return None

        conversation_id = f"conv_{merchant.merchant_id}_{trigger_id}"
        selection = select_candidate(
            [replace(ranked[0], candidate=top)],
            merchant,
            self.suppression,
            self.conversations,
            conversation_id,
            customer,
        )
        if not selection.selected:
            self._log(trigger_id, merchant.merchant_id, trigger.customer_id, _score_data(ranked), top.primary_signal, top.objective, f"selection_{selection.reason}", timer, plan.suppression_key, True)
            return None
        state = self.conversations.get_or_create(conversation_id, merchant.merchant_id, trigger.customer_id)
        state.sent_bodies.append(body)
        state.turns.append({"candidate_objective": top.objective, "trigger_id": trigger_id, "body": body})
        action = ComposedAction(
            conversation_id=conversation_id,
            merchant_id=merchant.merchant_id,
            customer_id=trigger.customer_id,
            send_as=plan.send_as,
            trigger_id=trigger_id,
            template_name=plan.template_name,
            template_params=[str(value) for value in params],
            body=body,
            cta=plan.cta,
            suppression_key=plan.suppression_key,
            rationale=plan.rationale,
        )
        self._log(trigger_id, merchant.merchant_id, trigger.customer_id, _score_data(ranked), top.primary_signal, top.objective, "selected", timer, plan.suppression_key, True)
        return action

    def _log(self, trigger_id, merchant_id, customer_id, scores, signal, action, outcome, timer, suppression_key=None, validation_passed=False, validation_reasons=()):
        if self.logger:
            self.logger.record(DecisionEvent(
                trigger_id=trigger_id,
                merchant_id=merchant_id,
                customer_id=customer_id,
                candidate_scores=tuple(scores),
                selected_signal=signal,
                selected_action=action,
                suppression_key=suppression_key,
                validation_passed=validation_passed,
                validation_reasons=tuple(validation_reasons),
                outcome=outcome,
                latency_ms=timer.elapsed_ms(),
            ))

    def _customer(self, trigger: TriggerContext) -> CustomerContext | None:
        if trigger.scope != "customer" or not trigger.customer_id:
            return None
        payload = self.contexts.payload("customer", trigger.customer_id)
        return CustomerContext.from_payload(payload) if payload else None


def action_to_dict(action: ComposedAction) -> dict[str, Any]:
    return {
        "conversation_id": action.conversation_id,
        "merchant_id": action.merchant_id,
        "customer_id": action.customer_id,
        "send_as": action.send_as,
        "trigger_id": action.trigger_id,
        "template_name": action.template_name,
        "template_params": action.template_params,
        "body": action.body,
        "cta": action.cta,
        "suppression_key": action.suppression_key,
        "rationale": action.rationale,
    }


def _score_data(ranked) -> list[dict[str, Any]]:
    return [{"objective": item.candidate.objective, "signal": item.candidate.primary_signal, "score": item.score} for item in ranked]