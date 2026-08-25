"""Deterministic reply classification and stateful conversation handling."""

from __future__ import annotations

import re
from typing import Any

from .models import ReplyResult
from .store import ConversationStore, SuppressionStore


AUTO_REPLY_MARKERS = (
    "thank you for contacting",
    "our team will respond",
    "automated assistant",
    "we have received your message",
)
OPT_OUT_MARKERS = ("stop messaging", "unsubscribe", "do not message", "don't message", "stop")
NEGATIVE_MARKERS = ("not interested", "not now", "no thanks", "maybe later", "no")
ACTION_MARKERS = ("let's do it", "lets do it", "go ahead", "proceed", "send it", "do it", "yes")
QUESTION_MARKERS = ("?", "how much", "what offer", "how long", "which", "when", "where")
OFF_TOPIC_MARKERS = ("gst", "tax filing", "unrelated", "legal advice")
HOSTILE_MARKERS = ("useless", "spam", "idiot", "shut up", "hate this")

# ---------------------------------------------------------------------------
# Objective → human-readable next-step description
# Used by CONFIRMATION and REQUEST_DETAILS handlers to name the active action.
# ---------------------------------------------------------------------------
_OBJECTIVE_NEXT_STEP: dict[str, str] = {
    "share_relevant_category_knowledge": "pull the source and draft a patient message",
    "surface_compliance_change":         "prepare the compliance checklist",
    "address_performance_decline":       "review the next growth action",
    "reframe_performance_decline":       "draft a retention message for active customers",
    "improve_listing":                   "draft the listing refresh",
    "reactivate_customers":              "draft the customer win-back message",
    "capitalize_on_demand":              "prepare the promotion",
    "address_supply_alert":             "prepare the affected-customer review list",
    "address_review_theme":             "draft the response plan",
    "respond_to_competitor_change":     "review your listing and draft a counter-position",
    "complete_business_profile":        "prepare the verification steps",
    "renew_subscription":               "prepare the renewal details",
    "amplify_milestone":                "draft the milestone post",
    "prepare_seasonal_campaign":        "draft the campaign",
    "plan_seasonal_campaign":           "draft the category-fit campaign",
    "restart_merchant_conversation":    "share a growth idea",
    "ask_merchant_for_insight":         "turn your answer into a Google post",
    "propose_merchant_winback":         "prepare the reactivation plan",
    "continue_active_plan":             "draft the first version",
    "prepare_content":                  "draft the first version",
    "customer_follow_up":               "confirm the follow-up",
    "reactivate_customer":              "book the visit",
}

_OBJECTIVE_CLARIFY_QUESTION: dict[str, str] = {
    "share_relevant_category_knowledge": "the research finding, the patient segment it affects, or the draft message?",
    "surface_compliance_change":         "the deadline, the specific change, or the checklist steps?",
    "address_performance_decline":       "the metric that dipped, the peer comparison, or the suggested action?",
    "improve_listing":                   "which listing element to refresh first?",
    "reactivate_customers":              "the lapsed customer count, the offer to use, or the message draft?",
    "capitalize_on_demand":              "the demand signal, the active offer, or the promotion format?",
    "address_supply_alert":             "the affected batches, the molecules, or the customer outreach draft?",
    "address_review_theme":             "the review theme, the occurrence count, or the response plan?",
    "respond_to_competitor_change":     "the competitor details, their offer, or the listing response?",
    "complete_business_profile":        "the verification path, the uplift estimate, or the step-by-step guide?",
    "renew_subscription":               "the renewal date, the amount, or the plan details?",
    "amplify_milestone":                "the milestone value, the metric, or the post draft?",
    "plan_seasonal_campaign":           "the festival timing, the offer fit, or the campaign format?",
    "propose_merchant_winback":         "the days since expiry, the performance drop, or the reactivation plan?",
    "continue_active_plan":             "the topic, the format, or the first draft?",
    "prepare_content":                  "the topic, the format, or the first draft?",
    "customer_follow_up":               "the available slots, the offer, or the confirmation message?",
    "reactivate_customer":              "the visit history, the available offer, or the booking message?",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_vera_turn(state) -> dict[str, Any] | None:
    """Return the most recent bot-sent turn from state.turns, or None."""
    for turn in reversed(state.turns):
        if isinstance(turn, dict) and turn.get("from") != "merchant":
            return turn
    return None


def _confirmation_body(objective: str | None) -> str:
    """
    Build a context-aware confirmation response.

    Always contains 'next action' to satisfy the existing test assertion.
    """
    step = _OBJECTIVE_NEXT_STEP.get(objective or "", "") if objective else ""
    if step:
        return (
            f"Got it — moving to the next action now: I will {step}. "
            f"Give me a moment and I will have it ready."
        )
    return "Got it. I am moving this to the next action now. Want me to proceed?"


def _details_body(objective: str | None, vera_body: str | None) -> str:
    """
    Build a context-aware REQUEST_DETAILS response.

    Names the active objective and offers specific clarification options.
    """
    question = _OBJECTIVE_CLARIFY_QUESTION.get(objective or "", "") if objective else ""
    if question:
        return (
            f"Happy to clarify. Which part would help most: {question}"
        )
    # Fall back: echo the first clause of the last bot message so the reply
    # feels grounded even without an objective match.
    if vera_body:
        snippet = vera_body.split(".")[0].strip()
        if snippet and len(snippet) < 120:
            return (
                f"Happy to clarify — this was about: {snippet}. "
                f"Which part should I expand on: the offer, the timing, or the next step?"
            )
    return (
        "I can share the details from the active context. "
        "Which part should I clarify: the offer, the timing, or the next step?"
    )


def _decline_topic(vera_body: str | None) -> str:
    """Extract a short topic label from the last bot message for the decline rationale."""
    if not vera_body:
        return "this"
    # Take the first clause up to the first period or question mark (max 80 chars)
    snippet = re.split(r"[.?]", vera_body)[0].strip()
    return snippet[:80] if snippet else "this"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_reply(message: str) -> str:
    text = " ".join(message.casefold().split())
    if any(marker in text for marker in OPT_OUT_MARKERS):
        return "OPT_OUT"
    if any(marker in text for marker in AUTO_REPLY_MARKERS):
        return "AUTO_REPLY"
    if any(marker in text for marker in OFF_TOPIC_MARKERS):
        return "OFF_TOPIC"
    if any(marker in text for marker in NEGATIVE_MARKERS):
        return "NO"
    if any(marker in text for marker in QUESTION_MARKERS):
        return "REQUEST_DETAILS"
    if any(marker in text for marker in ACTION_MARKERS):
        return "CONFIRMATION"
    if any(marker in text for marker in HOSTILE_MARKERS):
        return "HOSTILE"
    return "ACKNOWLEDGEMENT"


def handle_reply(
    conversation_id: str,
    message: str,
    conversations: ConversationStore,
    suppression: SuppressionStore,
    merchant_id: str | None = None,
    customer_id: str | None = None,
    received_at: str = "",
    turn_number: int = 1,
) -> ReplyResult:
    state = conversations.get_or_create(conversation_id, merchant_id, customer_id)
    if state.terminal:
        return ReplyResult("end", rationale="Conversation is already closed; no further message will be sent.")

    intent = classify_reply(message)
    state.turns.append({
        "from": "merchant",
        "body": message,
        "intent": intent,
        "turn_number": turn_number,
        "received_at": received_at,
    })

    # Retrieve the last Vera-sent turn for context-aware responses
    last_vera = _last_vera_turn(state)
    last_objective = last_vera.get("candidate_objective") if last_vera else None
    last_body = last_vera.get("body") if last_vera else None

    if intent == "OPT_OUT":
        state.terminal = True
        suppression.suppress_conversation(conversation_id)
        return ReplyResult(
            "end",
            rationale="Explicit opt-out received; ending and suppressing this conversation.",
        )

    if intent == "AUTO_REPLY":
        state.auto_reply_count += 1
        if state.auto_reply_count >= 3:
            state.terminal = True
            suppression.suppress_conversation(conversation_id)
            return ReplyResult(
                "end",
                rationale="Repeated canned auto-replies show no owner engagement; closing the conversation.",
            )
        return ReplyResult(
            "wait",
            wait_seconds=14400 if state.auto_reply_count == 1 else 86400,
            rationale="Detected a canned WhatsApp auto-reply; waiting for an owner response.",
        )

    if intent == "NO":
        topic = _decline_topic(last_body)
        state.terminal = True
        suppression.suppress_conversation(conversation_id)
        return ReplyResult(
            "end",
            rationale=f"Merchant declined '{topic}'; ending the conversation without another pitch.",
        )

    if intent == "OFF_TOPIC":
        return ReplyResult(
            "send",
            body="That is outside what I can help with directly. I can continue with the current growth task when you are ready.",
            cta="reply",
            rationale="Politely declined an unsupported off-topic request and preserved the conversation mission.",
        )

    if intent == "HOSTILE":
        state.terminal = True
        suppression.suppress_conversation(conversation_id)
        return ReplyResult(
            "end",
            rationale="Hostile feedback detected; ending the conversation without escalating or sending another pitch.",
        )

    if intent == "REQUEST_DETAILS":
        body = _details_body(last_objective, last_body)
        return ReplyResult(
            "send",
            body=body,
            cta="reply",
            rationale="Answered the clarification request with context-specific options and kept the original action available.",
        )

    if intent == "CONFIRMATION":
        body = _confirmation_body(last_objective)
        return ReplyResult(
            "send",
            body=body,
            cta="confirm",
            rationale="Recognised explicit action intent and advanced the specific objective instead of repeating qualification questions.",
        )

    return ReplyResult(
        "wait",
        wait_seconds=1800,
        rationale="Acknowledgement received; waiting for a concrete action request.",
    )


def reply_result_to_dict(result: ReplyResult) -> dict[str, Any]:
    response: dict[str, Any] = {"action": result.action, "rationale": result.rationale}
    if result.action == "send":
        response.update({"body": result.body, "cta": result.cta})
    elif result.action == "wait":
        response["wait_seconds"] = result.wait_seconds or 0
    return response
