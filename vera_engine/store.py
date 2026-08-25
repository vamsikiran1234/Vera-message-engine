"""In-memory state stores used by the Vera challenge service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Mapping

from .models import ContextEnvelope, ContextScope


VALID_SCOPES = frozenset({"category", "merchant", "customer", "trigger"})


class InvalidScopeError(ValueError):
    """Raised when a context push uses an unsupported scope."""


@dataclass(frozen=True)
class StoredContext:
    version: int
    payload: dict[str, Any]
    delivered_at: str


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: str | None = None
    customer_id: str | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)
    sent_bodies: list[str] = field(default_factory=list)
    suppression_keys: set[str] = field(default_factory=set)
    auto_reply_count: int = 0
    terminal: bool = False


class ContextStore:
    """Thread-safe latest-version store keyed by scope and context ID."""

    def __init__(self) -> None:
        self._contexts: dict[tuple[str, str], StoredContext] = {}
        self._lock = RLock()

    def put(self, envelope: ContextEnvelope) -> tuple[bool, int | None]:
        if envelope.scope not in VALID_SCOPES:
            raise InvalidScopeError(envelope.scope)
        key = (envelope.scope, envelope.context_id)
        with self._lock:
            current = self._contexts.get(key)
            if current is not None and current.version >= envelope.version:
                return False, current.version
            self._contexts[key] = StoredContext(
                version=envelope.version,
                payload=dict(envelope.payload),
                delivered_at=envelope.delivered_at,
            )
            return True, envelope.version

    def get(self, scope: ContextScope | str, context_id: str) -> StoredContext | None:
        with self._lock:
            return self._contexts.get((scope, context_id))

    def payload(self, scope: ContextScope | str, context_id: str) -> dict[str, Any] | None:
        stored = self.get(scope, context_id)
        return dict(stored.payload) if stored else None

    def counts(self) -> dict[str, int]:
        counts = {scope: 0 for scope in VALID_SCOPES}
        with self._lock:
            for scope, _ in self._contexts:
                counts[scope] += 1
        return counts


class ConversationStore:
    """Conversation state that survives across tick and reply requests."""

    def __init__(self) -> None:
        self._conversations: dict[str, ConversationState] = {}
        self._lock = RLock()

    def get_or_create(
        self,
        conversation_id: str,
        merchant_id: str | None = None,
        customer_id: str | None = None,
    ) -> ConversationState:
        with self._lock:
            state = self._conversations.setdefault(
                conversation_id,
                ConversationState(conversation_id, merchant_id, customer_id),
            )
            if merchant_id and not state.merchant_id:
                state.merchant_id = merchant_id
            if customer_id and not state.customer_id:
                state.customer_id = customer_id
            return state

    def add_turn(self, conversation_id: str, turn: Mapping[str, Any]) -> ConversationState:
        with self._lock:
            state = self.get_or_create(conversation_id)
            state.turns.append(dict(turn))
            return state


class SuppressionStore:
    """Tracks sent keys and explicit terminal suppression decisions."""

    def __init__(self) -> None:
        self._keys: set[str] = set()
        self._conversations: set[str] = set()
        self._lock = RLock()

    def contains(self, key: str) -> bool:
        with self._lock:
            return key in self._keys

    def add(self, key: str) -> None:
        if key:
            with self._lock:
                self._keys.add(key)

    def suppress_conversation(self, conversation_id: str) -> None:
        with self._lock:
            self._conversations.add(conversation_id)

    def conversation_suppressed(self, conversation_id: str) -> bool:
        with self._lock:
            return conversation_id in self._conversations


def utc_now() -> str:
    """Return a stable ISO-8601 UTC timestamp for API acknowledgements."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")