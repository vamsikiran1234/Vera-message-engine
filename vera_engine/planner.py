"""Build grounded message plans from selected candidate actions."""

from __future__ import annotations

from dataclasses import dataclass

from .candidates import CandidateAction
from .models import CategoryContext, CustomerContext, MerchantContext
from .signals import NormalizedTrigger


@dataclass(frozen=True)
class MessagePlan:
    objective: str
    primary_signal: str
    facts: dict
    cta: str
    send_as: str
    template_name: str
    suppression_key: str
    rationale: str


def build_message_plan(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    candidate: CandidateAction,
    customer: CustomerContext | None = None,
) -> MessagePlan:
    customer_send = trigger.scope == "customer" and customer is not None
    name = customer.identity.get("name") if customer_send else merchant.identity.get("owner_first_name")
    label = name or merchant.identity.get("name") or "there"
    rationale = f"Selected {candidate.objective} because {candidate.primary_signal} has grounded evidence from the current context."
    return MessagePlan(
        objective=candidate.objective,
        primary_signal=candidate.primary_signal,
        facts=dict(candidate.facts),
        cta=candidate.cta or "reply",
        send_as="merchant_on_behalf" if customer_send else "vera",
        template_name=_template_name(trigger.kind, customer_send),
        suppression_key=trigger.suppression_key or f"{merchant.merchant_id}:{trigger.kind}:{candidate.objective}",
        rationale=f"{rationale} Recipient: {label}.",
    )


def _template_name(kind: str, customer_send: bool) -> str:
    prefix = "merchant" if customer_send else "vera"
    safe_kind = kind or "signal"
    return f"{prefix}_{safe_kind}_v1"