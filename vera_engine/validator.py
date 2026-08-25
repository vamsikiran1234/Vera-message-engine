"""Deterministic validation for grounded Vera messages."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from .models import CategoryContext, CustomerContext, MerchantContext
from .planner import MessagePlan


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reasons: tuple[str, ...] = ()
    facts_checked: tuple[str, ...] = ()


def validate_message(
    body: str,
    cta: str,
    category: CategoryContext,
    merchant: MerchantContext,
    plan: MessagePlan,
    customer: CustomerContext | None = None,
    previous_bodies: list[str] | None = None,
) -> ValidationResult:
    reasons: list[str] = []
    checked: list[str] = []
    if not body.strip():
        reasons.append("empty_body")

    if customer and plan.send_as == "merchant_on_behalf" and not _has_consent(customer):
        reasons.append("customer_consent_missing")

    body_lower = body.casefold()
    for taboo in _taboos(category):
        if taboo.casefold() in body_lower:
            reasons.append(f"taboo_term:{taboo}")

    allowed_values = _grounded_values(category, merchant, plan, customer)
    for token in _factual_tokens(body):
        if token not in allowed_values:
            reasons.append(f"unsupported_fact:{token}")
        else:
            checked.append(token)

    if body.count("?") > 1:
        reasons.append("multiple_cta_questions")
    if cta and cta not in body_lower and cta not in {"none", "view", "reply"}:
        reasons.append("cta_not_reflected")

    if previous_bodies and body in previous_bodies:
        reasons.append("repeated_body")

    return ValidationResult(not reasons, tuple(reasons), tuple(checked))


def _has_consent(customer: CustomerContext) -> bool:
    scope = customer.consent.get("scope")
    return bool(customer.consent.get("opted_in_at") and isinstance(scope, list) and scope)


def _taboos(category: CategoryContext) -> list[str]:
    voice = category.voice
    values = voice.get("vocab_taboo", voice.get("taboos", []))
    return [str(value) for value in values] if isinstance(values, list) else []


def _grounded_values(
    category: CategoryContext,
    merchant: MerchantContext,
    plan: MessagePlan,
    customer: CustomerContext | None,
) -> set[str]:
    values: set[str] = set()
    for source in (category, merchant, plan, customer):
        _collect_strings(source, values)
    return {value.casefold() for value in values if value}


def _collect_strings(value: Any, output: set[str]) -> None:
    if is_dataclass(value):
        _collect_strings(asdict(value), output)
    elif isinstance(value, str):
        output.add(value.casefold())
        for number in re.findall(r"\d+(?:\.\d+)?", value):
            output.add(number.casefold())
    elif isinstance(value, dict):
        for item in value.values():
            _collect_strings(item, output)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_strings(item, output)
    elif isinstance(value, (int, float)):
        output.add(str(value).casefold())


def _factual_tokens(body: str) -> list[str]:
    return [token.casefold() for token in re.findall(r"\d+(?:\.\d+)?", body)]