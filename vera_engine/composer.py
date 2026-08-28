"""Optional, grounded LLM rewriting for approved merchant messages."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from dataclasses import fields, is_dataclass
from typing import Any, Mapping, Protocol
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .models import CategoryContext, MerchantContext
from .planner import MessagePlan
from .signals import NormalizedTrigger
from .validator import validate_message


DEFAULT_OBJECTIVES = frozenset({"perf_dip", "perf_spike", "renewal_due", "curious_ask_due"})


class ComposerProvider(Protocol):
    def complete(self, prompt: str, timeout: int) -> str:
        ...


@dataclass(frozen=True)
class Composition:
    message: str
    cta: str
    used_facts: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class CompositionDiagnostic:
    composition: Composition | None
    reason: str


class GeminiComposerProvider:
    def __init__(self, api_key: str, model: str, endpoint: str | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint or (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )

    def complete(self, prompt: str, timeout: int = 20) -> str:
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500},
        }).encode("utf-8")
        request = urlrequest.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urlrequest.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]


def compose_message(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
    deterministic_body: str,
    provider: ComposerProvider | None = None,
) -> Composition | None:
    """Return a validated rewrite, or None so the caller keeps the fallback."""
    return compose_message_diagnostic(
        category, merchant, trigger, plan, deterministic_body, provider
    ).composition


def compose_message_diagnostic(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
    deterministic_body: str,
    provider: ComposerProvider | None = None,
) -> CompositionDiagnostic:
    """Return a composition and a non-sensitive reason for its outcome."""
    if not composer_enabled() or not objective_allowed(trigger.kind):
        reason = "disabled" if not composer_enabled() else "not_allowlisted"
        return CompositionDiagnostic(None, reason)
    provider = provider or configured_provider()
    if provider is None:
        return CompositionDiagnostic(None, "provider_error")

    try:
        raw = provider.complete(_prompt(category, merchant, trigger, plan, deterministic_body), composer_timeout())
        normalized = _strip_outer_json_fence(raw)
        if normalized is None:
            return CompositionDiagnostic(None, "invalid_json")
        data = json.loads(normalized)
    except json.JSONDecodeError:
        return CompositionDiagnostic(None, "invalid_json")
    except HTTPError as error:
        return CompositionDiagnostic(None, f"provider_error:http_{error.code}")
    except TimeoutError:
        return CompositionDiagnostic(None, "provider_error:timeout")
    except (URLError, ConnectionError):
        return CompositionDiagnostic(None, "provider_error:network")
    except Exception:
        return CompositionDiagnostic(None, "provider_error:unknown")

    if not isinstance(data, dict) or set(data) != {"message", "cta", "used_facts", "confidence"}:
        return CompositionDiagnostic(None, "invalid_shape")
    try:
        result = Composition(
            message=data["message"],
            cta=data["cta"],
            used_facts=tuple(data["used_facts"]),
            confidence=float(data["confidence"]),
        )
    except (TypeError, ValueError, KeyError):
        return CompositionDiagnostic(None, "invalid_shape")

    if not _shape_is_valid(result):
        return CompositionDiagnostic(None, "invalid_shape")
    if result.cta != plan.cta:
        return CompositionDiagnostic(None, "cta_mismatch")
    grounding_reason = _grounding_failure_reason(result, category, merchant, trigger, plan)
    if grounding_reason:
        return CompositionDiagnostic(None, grounding_reason)
    quality_reason = _quality_failure_reason(result.message, deterministic_body, merchant, plan)
    if quality_reason:
        return CompositionDiagnostic(None, quality_reason)
    return CompositionDiagnostic(result, "accepted")


def composer_enabled() -> bool:
    return os.getenv("LLM_COMPOSER_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}


def objective_allowed(trigger_kind: str, allowlist: frozenset[str] | None = None) -> bool:
    configured = os.getenv("LLM_COMPOSER_OBJECTIVES", "")
    allowed = allowlist or (
        frozenset(item.strip() for item in configured.split(",") if item.strip())
        if configured.strip() else DEFAULT_OBJECTIVES
    )
    return trigger_kind in allowed


def configured_provider() -> ComposerProvider | None:
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_COMPOSER_MODEL", "") or os.getenv("GEMINI_MODELS", "").split(",")[0].strip()
    if not api_key or not model:
        return None
    return GeminiComposerProvider(api_key, model)


def composer_timeout() -> int:
    try:
        return max(1, min(60, int(os.getenv("LLM_COMPOSER_TIMEOUT_SECONDS", "20"))))
    except ValueError:
        return 20


def _strip_outer_json_fence(raw: str) -> str | None:
    text = raw.strip()
    if not text.startswith("```") and not text.endswith("```"):
        return text
    if not text.startswith("```") or not text.endswith("```"):
        return None
    match = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _prompt(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
    deterministic_body: str,
) -> str:
    fact_roots = _fact_roots(category, merchant, trigger, plan)
    valid_fact_paths: set[str] = set()
    for prefix, value in fact_roots.items():
        if prefix and not isinstance(value, (Mapping, list, tuple)) and not is_dataclass(value):
            valid_fact_paths.add(prefix.casefold())
        _collect_fact_paths(value, prefix, valid_fact_paths)
    grounded = {
        "merchant": merchant.identity,
        "conversation_context": merchant.conversation_history[-2:],
        "category": {"slug": category.slug, "voice": category.voice},
        "trigger_kind": trigger.kind,
        "objective": plan.objective,
        "facts": plan.facts,
        "evidence": {
            "primary_signal": plan.primary_signal,
            "merchant_hook": plan.merchant_hook,
            "category_hook": plan.category_hook,
            "supporting_facts": plan.supporting_facts,
        },
        "deterministic_message": deterministic_body,
        "deterministic_cta": plan.cta,
        "valid_used_fact_paths": sorted(valid_fact_paths),
    }
    return (
        "You are rewriting an approved Vera merchant message for specificity, category fit, "
        "merchant fit, decision quality, and engagement. Lead with the strongest grounded "
        "facts, explain why this matters now, use natural fellow-operator language, and end "
        "with one clear concrete CTA. Use conversation context only when supplied. Do not add "
        "facts. Do not change the recommended action. Do not invent numbers, offers, dates, "
        "competitors, customer counts, locations, business outcomes, social proof, or urgency. "
        "Preserve every grounded numeric fact, percentage, currency amount, timing detail, "
        "offer name, merchant name, and required uncertainty marker such as 'likely'. "
        "Use light Hindi-English only when the merchant language preference supports it. "
        "Use only the grounded context below. The generated message MUST naturally express "
        "the supplied CTA action. For draft, explicitly offer to draft, create, or prepare; "
        "for send, explicitly offer to send or share; for approve, explicitly ask to approve "
        "or proceed; for confirm, explicitly ask to confirm. Do not change the action. "
        "Return used_facts using only the exact paths listed in valid_used_fact_paths. "
        "Return at most one customer-facing question. "
        "Return JSON only with exactly these fields: message, cta, used_facts, confidence.\n"
        + json.dumps(grounded, ensure_ascii=False, default=str)
    )


def _shape_is_valid(result: Composition) -> bool:
    return (
        isinstance(result.message, str)
        and bool(result.message.strip())
        and isinstance(result.cta, str)
        and isinstance(result.used_facts, tuple)
        and all(isinstance(item, str) for item in result.used_facts)
        and 0.0 <= result.confidence <= 1.0
        and "```" not in result.message
        and result.message.count("?") <= 1
        and len(result.message.split()) <= 80
    )


def _quality_failure_reason(
    composed: str,
    deterministic: str,
    merchant: MerchantContext,
    plan: MessagePlan,
) -> str | None:
    if composed == deterministic:
        return "quality_failed:unchanged"
    composed_lower = composed.casefold()
    deterministic_lower = deterministic.casefold()
    if any(phrase in composed_lower for phrase in ("want help?", "your business is doing well", "unlock growth", "leverage this opportunity", "drive conversions")):
        return "quality_failed:generic"
    if len(composed.split()) > 80:
        return "quality_failed:unnecessarily_long"
    if "likely" in deterministic_lower and "likely" not in composed_lower:
        return "quality_failed:uncertainty_removed"
    if "peer" in deterministic_lower and "peer" not in composed_lower:
        return "quality_failed:peer_comparison_removed"
    for token in re.findall(r"\b\d+(?:\.\d+)?%?\b", deterministic):
        if token.casefold() not in composed_lower:
            return "quality_failed:grounded_number_removed"
    for amount in re.findall(r"(?:₹|Rs\.?\s*)(\d+(?:\.\d+)?)", deterministic, re.IGNORECASE):
        if not _contains_number(amount, composed_lower):
            return "quality_failed:grounded_currency_removed"
    for offer in merchant.offers:
        title = str(offer.get("title") or "")
        if title and title.casefold() in deterministic_lower and title.casefold() not in composed_lower:
            return "quality_failed:offer_removed"
    for date in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", deterministic):
        if date.casefold() not in composed_lower:
            return "quality_failed:timing_removed"
    return None


def _grounded(
    result: Composition,
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
    deterministic_body: str,
) -> bool:
    return _grounding_failure_reason(result, category, merchant, trigger, plan) is None


def _grounding_failure_reason(
    result: Composition,
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
) -> str | None:
    validation = validate_message(result.message, plan.cta, category, merchant, plan)
    rejected_facts = [reason for reason in validation.reasons if reason.startswith("unsupported_fact:")]
    if not validation.valid and any(
        reason not in rejected_facts for reason in validation.reasons
    ):
        return "validation_failed"
    grounded_text = json.dumps(
        {"category": category, "merchant": merchant, "trigger": trigger, "plan": plan},
        ensure_ascii=False,
        default=str,
    ).casefold()
    fact_roots = _fact_roots(category, merchant, trigger, plan)
    for fact_path in result.used_facts:
        value = _resolve_fact_path(fact_roots, fact_path)
        if value is _MISSING or not _value_is_grounded_in_message(value, result.message):
            return "grounding_failed:used_fact"
    owner = str(merchant.identity.get("owner_first_name") or "").strip()
    if owner and owner.casefold() not in result.message.casefold():
        return "grounding_failed:merchant_name"
    for token in re.findall(r"\b\d+(?:\.\d+)?\b", result.message):
        if not _contains_number(token, grounded_text) and not _percentage_is_grounded(token, grounded_text):
            return "grounding_failed:number"
    for amount in re.findall(r"(?:₹|Rs\.?\s*)(\d+(?:\.\d+)?)", result.message, re.IGNORECASE):
        if not _contains_number(amount, grounded_text):
            return "grounding_failed:currency"
    return None


_MISSING = object()


def _fact_roots(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    plan: MessagePlan,
) -> dict[str, Any]:
    facts = dict(plan.facts)
    performance = facts.get("performance")
    if isinstance(performance, Mapping):
        performance = dict(performance)
        for key in ("metric", "delta_pct", "vs_baseline"):
            if key not in performance and key in trigger.facts:
                performance[key] = trigger.facts[key]
        facts["performance"] = performance
    return {
        **facts,
        "category": category,
        "merchant": merchant,
        "trigger": trigger,
        "plan": plan,
    }


def _resolve_fact_path(roots: Mapping[str, Any], path: str) -> Any:
    current: Any = roots
    parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    for part in parts:
        if part.startswith("["):
            if not isinstance(current, (list, tuple)):
                return _MISSING
            index = int(part[1:-1])
            if index >= len(current):
                return _MISSING
            current = current[index]
            continue
        if isinstance(current, Mapping):
            if part not in current:
                return _MISSING
            current = current[part]
        elif is_dataclass(current):
            if not hasattr(current, part):
                return _MISSING
            current = getattr(current, part)
        else:
            return _MISSING
    return current


def _value_is_grounded_in_message(value: Any, message: str) -> bool:
    if isinstance(value, Mapping):
        return any(_value_is_grounded_in_message(item, message) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_value_is_grounded_in_message(item, message) for item in value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(value)
        percentage = f"{abs(float(value)) * 100:g}"
        return (
            _contains_number(text, message.casefold())
            or _contains_number(percentage, message.casefold())
        )
    text = str(value).strip()
    return bool(text) and text.casefold().replace("_", " ") in message.casefold()


def _collect_fact_paths(value: Any, prefix: str, paths: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path.casefold())
            _collect_fact_paths(child, path, paths)
        return
    if is_dataclass(value):
        for field in fields(value):
            path = f"{prefix}.{field.name}" if prefix else field.name
            paths.add(path.casefold())
            _collect_fact_paths(getattr(value, field.name), path, paths)
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _collect_fact_paths(child, f"{prefix}[{index}]", paths)


def _contains_number(token: str, grounded_text: str) -> bool:
    return re.search(rf"(?<!\d){re.escape(token.casefold())}(?!\d)", grounded_text) is not None


def _percentage_is_grounded(token: str, grounded_text: str) -> bool:
    try:
        decimal = str(float(token) / 100).rstrip("0").rstrip(".")
        return _contains_number(decimal, grounded_text)
    except ValueError:
        return False
