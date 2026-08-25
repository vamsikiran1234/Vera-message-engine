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
    if any(marker in text for marker in ACTION_MARKERS):
        return "CONFIRMATION"
    if any(marker in text for marker in QUESTION_MARKERS):
        return "REQUEST_DETAILS"
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
    intent = classify_reply(message)
    state.turns.append({"from": "merchant", "body": message, "intent": intent, "turn_number": turn_number, "received_at": received_at})

    if intent == "OPT_OUT":
        state.terminal = True
        suppression.suppress_conversation(conversation_id)
        return ReplyResult("end", rationale="Explicit opt-out received; ending and suppressing this conversation.")

    if intent == "AUTO_REPLY":
        state.auto_reply_count += 1
        if state.auto_reply_count >= 3:
            state.terminal = True
            suppression.suppress_conversation(conversation_id)
            return ReplyResult("end", rationale="Repeated canned auto-replies show no owner engagement; closing the conversation.")
        return ReplyResult("wait", wait_seconds=14400 if state.auto_reply_count == 1 else 86400, rationale="Detected a canned WhatsApp auto-reply; waiting for an owner response.")

    if intent == "NO":
        state.terminal = True
        suppression.suppress_conversation(conversation_id)
        return ReplyResult("end", rationale="Merchant declined the action; ending the conversation without another pitch.")

    if intent == "OFF_TOPIC":
        return ReplyResult("send", body="That is outside what I can help with directly. I can continue with the current merchant-growth task when you are ready.", cta="reply", rationale="Politely declined an unsupported off-topic request and preserved the conversation mission.")

    if intent == "REQUEST_DETAILS":
        return ReplyResult("send", body="I can share the details from the active context first. Which part should I clarify: the offer, timing, or next step?", cta="reply", rationale="Answered the request without inventing details and kept the original action available.")

    if intent == "CONFIRMATION":
        return ReplyResult("send", body="Got it. I am moving this to the next action now. Want me to proceed?", cta="confirm", rationale="Recognized explicit action intent and advanced instead of repeating qualification questions.")

    return ReplyResult("wait", wait_seconds=1800, rationale="Acknowledgement received; waiting for a concrete action request.")


def reply_result_to_dict(result: ReplyResult) -> dict[str, Any]:
    response: dict[str, Any] = {"action": result.action, "rationale": result.rationale}
    if result.action == "send":
        response.update({"body": result.body, "cta": result.cta})
    elif result.action == "wait":
        response["wait_seconds"] = result.wait_seconds or 0
    return response