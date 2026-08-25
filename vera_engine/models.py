"""Typed domain models for the four Vera context layers and API state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


ContextScope = Literal["category", "merchant", "customer", "trigger"]
SendAs = Literal["vera", "merchant_on_behalf"]
ReplyAction = Literal["send", "wait", "end"]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


@dataclass(frozen=True)
class ContextEnvelope:
    scope: ContextScope
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


@dataclass(frozen=True)
class CategoryContext:
    slug: str
    display_name: str = ""
    voice: dict[str, Any] = field(default_factory=dict)
    offer_catalog: list[dict[str, Any]] = field(default_factory=list)
    peer_stats: dict[str, Any] = field(default_factory=dict)
    digest: list[dict[str, Any]] = field(default_factory=list)
    patient_content_library: list[dict[str, Any]] = field(default_factory=list)
    seasonal_beats: list[dict[str, Any]] = field(default_factory=list)
    trend_signals: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CategoryContext":
        data = dict(payload)
        known = {
            "slug", "display_name", "voice", "offer_catalog", "peer_stats",
            "digest", "patient_content_library", "seasonal_beats", "trend_signals",
        }
        return cls(
            slug=str(data.get("slug", "")),
            display_name=str(data.get("display_name", "")),
            voice=_mapping(data.get("voice")),
            offer_catalog=[_mapping(item) for item in _list(data.get("offer_catalog"))],
            peer_stats=_mapping(data.get("peer_stats")),
            digest=[_mapping(item) for item in _list(data.get("digest"))],
            patient_content_library=[_mapping(item) for item in _list(data.get("patient_content_library"))],
            seasonal_beats=[_mapping(item) for item in _list(data.get("seasonal_beats"))],
            trend_signals=[_mapping(item) for item in _list(data.get("trend_signals"))],
            extra={key: value for key, value in data.items() if key not in known},
        )


@dataclass(frozen=True)
class MerchantContext:
    merchant_id: str
    category_slug: str
    identity: dict[str, Any] = field(default_factory=dict)
    subscription: dict[str, Any] = field(default_factory=dict)
    performance: dict[str, Any] = field(default_factory=dict)
    offers: list[dict[str, Any]] = field(default_factory=list)
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    customer_aggregate: dict[str, Any] = field(default_factory=dict)
    signals: list[Any] = field(default_factory=list)
    review_themes: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MerchantContext":
        data = dict(payload)
        known = {
            "merchant_id", "category_slug", "identity", "subscription", "performance",
            "offers", "conversation_history", "customer_aggregate", "signals", "review_themes",
        }
        return cls(
            merchant_id=str(data.get("merchant_id", "")),
            category_slug=str(data.get("category_slug", "")),
            identity=_mapping(data.get("identity")),
            subscription=_mapping(data.get("subscription")),
            performance=_mapping(data.get("performance")),
            offers=[_mapping(item) for item in _list(data.get("offers"))],
            conversation_history=[_mapping(item) for item in _list(data.get("conversation_history"))],
            customer_aggregate=_mapping(data.get("customer_aggregate")),
            signals=_list(data.get("signals")),
            review_themes=[_mapping(item) for item in _list(data.get("review_themes"))],
            extra={key: value for key, value in data.items() if key not in known},
        )


@dataclass(frozen=True)
class CustomerContext:
    customer_id: str
    merchant_id: str
    identity: dict[str, Any] = field(default_factory=dict)
    relationship: dict[str, Any] = field(default_factory=dict)
    state: str = ""
    preferences: dict[str, Any] = field(default_factory=dict)
    consent: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CustomerContext":
        data = dict(payload)
        known = {
            "customer_id", "merchant_id", "identity", "relationship", "state",
            "preferences", "consent",
        }
        return cls(
            customer_id=str(data.get("customer_id", "")),
            merchant_id=str(data.get("merchant_id", "")),
            identity=_mapping(data.get("identity")),
            relationship=_mapping(data.get("relationship")),
            state=str(data.get("state", "")),
            preferences=_mapping(data.get("preferences")),
            consent=_mapping(data.get("consent")),
            extra={key: value for key, value in data.items() if key not in known},
        )


@dataclass(frozen=True)
class TriggerContext:
    trigger_id: str
    scope: str
    kind: str
    source: str
    merchant_id: str
    customer_id: str | None
    payload: dict[str, Any]
    urgency: int
    suppression_key: str
    expires_at: str
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TriggerContext":
        data = dict(payload)
        known = {
            "id", "scope", "kind", "source", "merchant_id", "customer_id", "payload",
            "urgency", "suppression_key", "expires_at",
        }
        try:
            urgency = int(data.get("urgency", 0))
        except (TypeError, ValueError):
            urgency = 0
        customer_id = data.get("customer_id")
        return cls(
            trigger_id=str(data.get("id", "")),
            scope=str(data.get("scope", "merchant")),
            kind=str(data.get("kind", "")),
            source=str(data.get("source", "")),
            merchant_id=str(data.get("merchant_id", "")),
            customer_id=str(customer_id) if customer_id is not None else None,
            payload=_mapping(data.get("payload")),
            urgency=urgency,
            suppression_key=str(data.get("suppression_key", "")),
            expires_at=str(data.get("expires_at", "")),
            extra={key: value for key, value in data.items() if key not in known},
        )


@dataclass(frozen=True)
class ComposedAction:
    conversation_id: str
    merchant_id: str
    customer_id: str | None
    send_as: SendAs
    trigger_id: str
    template_name: str
    template_params: list[str]
    body: str
    cta: str
    suppression_key: str
    rationale: str


@dataclass(frozen=True)
class ReplyResult:
    action: ReplyAction
    body: str = ""
    cta: str = ""
    wait_seconds: int | None = None
    rationale: str = ""