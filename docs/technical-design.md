# Vera Message Engine - Technical Design

Status: Phase 3 design baseline
Branch: vamsi

## 1. Objective

Implement a deterministic HTTP service that receives versioned category, merchant, customer, and trigger contexts; selects the highest-value action; composes a grounded message; and maintains suppression and conversation state.

The official challenge contract is authoritative. Required paths are `/v1/healthz`, `/v1/metadata`, `/v1/context`, `/v1/tick`, and `/v1/reply`.

## 2. Runtime Architecture

```text
FastAPI routes
    -> request validation
    -> ContextStore
    -> ConversationStore
    -> TickCoordinator
         -> context resolution
         -> signal extraction
         -> candidate generation
         -> deterministic scoring
         -> suppression/conflict filtering
         -> message planning
         -> template rendering
         -> grounding/CTA validation
    -> response serialization
```

Initial implementation will be a single Python service with in-memory stores. The store interfaces will isolate persistence so SQLite can be added later without changing decision logic.

## 3. Proposed Modules

```text
bot.py                         FastAPI application and route wiring
vera_engine/
  models.py                    Typed request, context, action, and state models
  store.py                     Versioned contexts, suppression, and conversations
  normalize.py                 Defensive access and normalized context views
  categories.py                Category policy lookup and generic fallback policy
  signals.py                   Trigger/merchant/customer signal extraction
  scoring.py                   Candidate scoring and stable tie-breaking
  selection.py                 Deduplication, opt-out, and conflict rules
  planner.py                   Action and message-plan construction
  templates.py                 Deterministic category-aware message renderers
  validator.py                 Grounding, CTA, safety, and repetition checks
  replies.py                   Reply intent classification and state transitions
  observability.py             Structured decision logging

tests/
  test_store.py
  test_decision_engine.py
  test_templates.py
  test_replies.py
  test_api.py
```

## 4. Context and State Model

`ContextStore` keys contexts by `(scope, context_id)` and stores the latest version, payload, and delivery timestamp.

Rules:

- Unknown scopes are rejected with a validation error.
- A higher version atomically replaces the stored value.
- An equal or lower version is rejected as `stale_version` with HTTP 409, matching the official examples.
- Payload fields remain permissive so unknown fields do not break ingestion.
- Tick processing reads one consistent snapshot of the relevant contexts.

`ConversationStore` stores conversation ID, merchant/customer IDs, sent bodies, trigger/action metadata, reply turns, intent, auto-reply count, and terminal status.

`SuppressionStore` tracks suppression keys and conversation-level suppression. It prevents duplicate trigger actions, repeated bodies, opted-out recipients, and recently rejected actions.

## 5. Tick Decision Pipeline

For each available trigger, in request order:

1. Resolve the trigger context.
2. Resolve its merchant and category.
3. Resolve its customer when the trigger is customer-scoped.
4. Reject expired or structurally invalid triggers.
5. Extract only facts present in the received contexts.
6. Generate candidate actions based on trigger kind and available facts.
7. Score candidates using configurable deterministic weights.
8. Apply opt-out, duplicate, recent-action, and conflict suppression.
9. Rank by score, then by fixed action priority, then by trigger ID for stable ties.
10. Select at most one action per trigger and no more than 20 actions per tick.
11. Render a message plan and deterministic template output.
12. Validate grounding, CTA count, category safety, and repetition.
13. Persist the action and suppression key before returning it.

Unknown triggers use a conservative generic candidate only when the trigger payload or merchant state contains a concrete fact. Otherwise they produce no action.

## 6. Candidate Scoring

Weights will live in configuration rather than route code. Initial score components:

```text
trigger_strength       0.25
merchant_impact        0.20
category_fit           0.15
actionability          0.15
customer_relevance     0.10
urgency                0.10
specificity            0.05
```

Penalties:

- recent matching suppression key
- recent message on the same topic
- merchant rejection or customer opt-out
- missing evidence for the candidate
- conflict with a stronger active action

Stable ordering is mandatory. The engine will never use random selection or an LLM for action choice.

## 7. Category Policies

Policies are data-driven and keyed by category slug:

- tone and register
- preferred salutations
- allowed vocabulary
- taboo/safety terms
- preferred action types and CTAs
- customer-facing style
- relevant trigger families

The five supplied category contexts provide the primary policy data. An unknown category receives a neutral, factual fallback policy rather than failing or pretending to know category-specific rules.

## 8. Message Planning and Rendering

The planner produces:

```text
objective
primary_signal
facts_to_use
value_or_offer
urgency
cta_type
send_as
template_name
suppression_key
rationale
```

Rendering is deterministic and uses only selected facts. Merchant-facing actions use `send_as: "vera"`. Customer-scoped actions require a valid customer, valid consent, and use `send_as: "merchant_on_behalf"`.

The first-touch response includes a stable template name and ordered parameters. Later conversation replies may use free-form deterministic templates.

Every message has one primary CTA. Pure information triggers may use `none`; action triggers use a single approval, booking, promotion, confirmation, or reply CTA.

## 9. Grounding and Safety Validation

Validation will check:

- Numeric values, prices, dates, names, offers, and locations are sourced from current contexts.
- Expired offers are never presented as active.
- Customer messages do not use customer data without consent.
- Pharmacy and healthcare messages avoid unsupported medical guarantees or treatment claims.
- Taboo category terms are removed or cause a safe fallback.
- The final message is non-empty and concise.
- The CTA field is consistent with the message's final ask.
- The body is not a prior body in the same conversation.

If validation fails, the renderer falls back to a shorter plan using only a verified trigger fact and one CTA. If no safe plan remains, the action is omitted.

## 10. Reply Handling

Reply classification is deterministic and ordered from highest-risk/highest-confidence intents:

1. OPT_OUT / stop / unsubscribe
2. explicit negative or defer
3. explicit confirmation or action intent
4. question/request for details
5. off-topic or hostile content
6. generic acknowledgement

State transitions:

- OPT_OUT -> persist suppression and return `end`.
- Repeated canned auto-reply -> `wait`, then `end` after the configured threshold.
- Explicit action intent -> produce the next action immediately; do not re-qualify.
- Question -> answer from stored contexts and preserve the original objective.
- Off-topic request -> politely decline unsupported work and redirect once; end if the conversation remains off-topic.
- Generic acknowledgement -> continue only when a concrete next step is available.

## 11. API and Operational Design

- FastAPI with strict outer request models and permissive context payload dictionaries.
- All handlers return JSON matching the official response shapes.
- `/v1/tick` returns quickly and never performs network calls.
- `/v1/healthz` reports uptime and per-scope context counts.
- `/v1/metadata` reads non-secret metadata from environment variables with deterministic defaults.
- The service listens on `0.0.0.0` and uses `PORT`, defaulting to `8080`.
- No LLM or external API is required for the baseline implementation.

## 12. Testing Strategy

Unit tests will cover context versioning, normalization, candidate scoring, category policies, suppression, grounding, CTA selection, reply intents, and state transitions.

API tests will cover all five endpoints, malformed inputs, duplicate versions, version upgrades, customer consent, action limits, and unknown fields.

Fixture tests will load `expanded/` and exercise all 30 canonical pairs without hardcoding expected message text.

Adversarial tests will cover placeholder triggers, expired triggers, conflicting signals, unknown categories, missing customers, opt-outs, auto-replies, hostile replies, repeated messages, and large payloads.

Validation commands after implementation:

```powershell
python -m pytest
python -m compileall bot.py vera_engine tests
python judge_simulator.py
```

## 13. Deployment and Configuration

Required documentation will include:

```text
PORT=8080
TEAM_NAME=Vera Growth Engine
TEAM_MEMBERS=...
CONTACT_EMAIL=...
VERSION=0.1.0
```

Startup command:

```powershell
uvicorn bot:app --host 0.0.0.0 --port 8080
```

The deployment must expose the five `/v1/*` endpoints through one public URL. Secrets, if an optional LLM is added later, must be supplied through environment variables and excluded from source control.

## 14. Design Decisions and Tradeoffs

- Deterministic templates are preferred over an LLM because the challenge rewards grounded decisions and stable output.
- In-memory state is sufficient for the judge process and minimizes latency; a storage interface keeps SQLite migration possible.
- Candidate scoring is explicit and configurable so judge feedback can tune decisions without rewriting rendering.
- Conservative omission is preferred over a fabricated message when evidence is incomplete.
- The official HTTP contract takes precedence over the conceptual PRD response shape.
