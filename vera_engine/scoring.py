"""Deterministic scoring and ranking for candidate Vera actions."""

from __future__ import annotations

from dataclasses import dataclass

from .candidates import CandidateAction
from .models import CategoryContext, CustomerContext, MerchantContext
from .signals import NormalizedTrigger, Signal


@dataclass(frozen=True)
class ScoringWeights:
    trigger_strength: float = 0.25
    merchant_impact: float = 0.20
    category_fit: float = 0.15
    actionability: float = 0.15
    customer_relevance: float = 0.10
    urgency: float = 0.10
    specificity: float = 0.05
    merchant_relevance: float = 0.05
    offer_compatibility: float = 0.05
    conversation_continuity: float = 0.05
    evidence_strength: float = 0.05


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: CandidateAction
    score: float
    components: dict[str, float]


def score_candidate(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    candidate: CandidateAction,
    signals: list[Signal],
    customer: CustomerContext | None = None,
    weights: ScoringWeights | None = None,
) -> ScoredCandidate:
    weights = weights or ScoringWeights()
    signal = next((item for item in signals if item.name == candidate.primary_signal), None)
    components = {
        "trigger_strength": _bounded(trigger.urgency / 5),
        "merchant_impact": _merchant_impact(merchant, candidate),
        "category_fit": _category_fit(category, trigger, candidate),
        "actionability": _bounded(candidate.priority_hint / 100),
        "customer_relevance": 1.0 if customer and trigger.scope == "customer" else 0.0,
        "urgency": _bounded(trigger.urgency / 5),
        "specificity": _bounded((signal.specificity if signal else 0) / 4),
        "merchant_relevance": _bounded(len(candidate.merchant_evidence) / 3),
        "offer_compatibility": _bounded(len(candidate.offer_evidence) / 2),
        "conversation_continuity": _bounded(len(candidate.conversation_evidence) / 2),
        "evidence_strength": _bounded((len(candidate.evidence) + len(candidate.category_evidence) + len(candidate.merchant_evidence)) / 5),
    }
    score = sum(components[name] * getattr(weights, name) for name in components)
    return ScoredCandidate(candidate=candidate, score=round(score, 6), components=components)


def rank_candidates(
    category: CategoryContext,
    merchant: MerchantContext,
    trigger: NormalizedTrigger,
    candidates: list[CandidateAction],
    signals: list[Signal],
    customer: CustomerContext | None = None,
    weights: ScoringWeights | None = None,
) -> list[ScoredCandidate]:
    scored = [score_candidate(category, merchant, trigger, candidate, signals, customer, weights) for candidate in candidates]
    return sorted(
        scored,
        key=lambda item: (-item.score, -item.candidate.priority_hint, item.candidate.action_type, item.candidate.primary_signal),
    )


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def _merchant_impact(merchant: MerchantContext, candidate: CandidateAction) -> float:
    score = 0.2 if merchant.merchant_id else 0.0
    score += 0.3 if merchant.identity.get("name") else 0.0
    score += 0.25 if merchant.offers else 0.0
    score += 0.25 if candidate.facts else 0.0
    return _bounded(score)


def _category_fit(category: CategoryContext, trigger: NormalizedTrigger, candidate: CandidateAction) -> float:
    if not category.slug:
        return 0.0
    tone = str(category.voice.get("tone", ""))
    fit = 0.4
    if tone:
        fit += 0.2
    if trigger.kind in {"research_digest", "regulation_change", "cde_opportunity"} and category.digest:
        fit += 0.4
    elif trigger.kind in {"recall_due", "customer_lapsed_soft", "customer_lapsed_hard"}:
        fit += 0.3
    elif candidate.action_type in {"recommend", "customer_outreach"}:
        fit += 0.2
    return _bounded(fit)