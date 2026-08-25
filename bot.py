"""FastAPI entrypoint for the Vera message engine."""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from vera_engine.engine import DecisionEngine, action_to_dict
from vera_engine.models import ContextEnvelope
from vera_engine.replies import handle_reply, reply_result_to_dict
from vera_engine.store import ContextStore, ConversationStore, InvalidScopeError, SuppressionStore, utc_now


START_TIME = time.time()
app = FastAPI(title="Vera Message Engine")
context_store = ContextStore()
conversation_store = ConversationStore()
suppression_store = SuppressionStore()


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scope: str
    context_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    payload: dict[str, Any]
    delivered_at: str


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    now: str
    available_triggers: list[str] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conversation_id: str = Field(min_length=1)
    merchant_id: str | None = None
    customer_id: str | None = None
    from_role: str
    message: str
    received_at: str
    turn_number: int = Field(ge=1)


@app.get("/healthz")
@app.get("/v1/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": context_store.counts(),
    }


@app.get("/metadata")
@app.get("/v1/metadata")
def metadata() -> dict[str, Any]:
    members = [item.strip() for item in os.getenv("TEAM_MEMBERS", "Vera Team").split(",") if item.strip()]
    return {
        "team_name": os.getenv("TEAM_NAME", "Vera Growth Engine"),
        "team_members": members,
        "model": "deterministic-templates",
        "approach": "deterministic context-grounded decision engine",
        "contact_email": os.getenv("CONTACT_EMAIL", ""),
        "version": os.getenv("VERSION", "0.1.0"),
        "submitted_at": os.getenv("SUBMITTED_AT", ""),
    }


@app.post("/v1/context", status_code=200)
def push_context(body: ContextRequest) -> dict[str, Any]:
    try:
        envelope = ContextEnvelope(
            scope=body.scope,
            context_id=body.context_id,
            version=body.version,
            payload=body.payload,
            delivered_at=body.delivered_at,
        )
        accepted, current_version = context_store.put(envelope)
    except InvalidScopeError as exc:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_scope", "details": str(exc)},
        )

    if not accepted:
        return JSONResponse(
            status_code=409,
            content={"accepted": False, "reason": "stale_version", "current_version": current_version},
        )
    return {"accepted": True, "ack_id": f"ack_{body.context_id}_v{body.version}", "stored_at": utc_now()}


@app.post("/v1/tick")
def tick(body: TickRequest) -> dict[str, list[Any]]:
    engine = DecisionEngine(context_store, conversation_store, suppression_store)
    actions = []
    for trigger_id in body.available_triggers:
        if len(actions) >= 20:
            break
        action = engine.compose_trigger(trigger_id)
        if action:
            actions.append(action_to_dict(action))
    return {"actions": actions}


@app.post("/v1/reply")
def reply(body: ReplyRequest) -> dict[str, Any]:
    result = handle_reply(
        body.conversation_id,
        body.message,
        conversation_store,
        suppression_store,
        body.merchant_id,
        body.customer_id,
        body.received_at,
        body.turn_number,
    )
    return reply_result_to_dict(result)
