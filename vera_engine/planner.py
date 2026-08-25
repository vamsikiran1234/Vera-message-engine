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
    supporting_facts: dict = None
    merchant_hook: str = ""
    category_hook: str = ""
    value_delivered: str = ""


def build_message_plan(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    candidate: CandidateAction,
    customer: CustomerContext | None = None,
    enriched_facts: dict | None = None,
) -> MessagePlan:
    customer_send = trigger.scope == "customer" and customer is not None
    name = customer.identity.get("name") if customer_send else merchant.identity.get("owner_first_name")
    label = name or merchant.identity.get("name") or "there"
    rationale = f"Selected {candidate.objective} because {candidate.primary_signal} has grounded evidence from the current context."
    merchant_hook = candidate.merchant_evidence[0] if candidate.merchant_evidence else ""
    category_hook = candidate.category_evidence[0] if candidate.category_evidence else ""
    value_delivered = "a ready-to-use follow-up" if candidate.action_type in {"recommend", "customer_outreach"} else "the relevant source context"
    # Use enriched_facts when provided (evidence selection output); fall back to candidate.facts
    facts = enriched_facts if enriched_facts is not None else dict(candidate.facts)
    return MessagePlan(
        objective=candidate.objective,
        primary_signal=candidate.primary_signal,
        facts=facts,
        cta=candidate.cta or "reply",
        send_as="merchant_on_behalf" if customer_send else "vera",
        template_name=_template_name(trigger.kind, customer_send),
        suppression_key=trigger.suppression_key or f"{merchant.merchant_id}:{trigger.kind}:{candidate.objective}",
        rationale=f"{rationale} Recipient: {label}.",
        supporting_facts=facts,
        merchant_hook=merchant_hook,
        category_hook=category_hook,
        value_delivered=value_delivered,
    )


def _template_name(kind: str, customer_send: bool) -> str:
    prefix = "merchant" if customer_send else "vera"
    safe_kind = kind or "signal"
    return f"{prefix}_{safe_kind}_v1"