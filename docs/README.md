Vera Message Engine

A deterministic, context-grounded merchant-growth message engine built for the magicpin AI Challenge.

Vera receives category, merchant, trigger, and optional customer context, selects the most useful action, and produces a concise merchant-facing message with one clear CTA.

Design Principles

Grounded: every claim should come from supplied context.

Deterministic: candidate generation, ranking, evidence selection, suppression, and planning are reproducible.

Specific: use real metrics, offers, timing, and merchant facts.

Actionable: one strong reason to respond and one low-effort CTA.

Safe fallback: invalid or unavailable LLM output never blocks a deterministic response.

Architecture

HTTP API
   |
Versioned Context Store
   |
Signal Extraction / Normalization
   |
Candidate Generation
   |
Deterministic Ranking & Selection
   |
Evidence Selection + Suppression
   |
MessagePlan
   |
Deterministic Render
   |
Optional LLM Composer
   |
Grounding / CTA / Safety Validation
   |
Final Action

The core implementation lives in vera_engine/; bot.py is the FastAPI entrypoint.

Decision pipeline

Receive and version category, merchant, customer, and trigger contexts.

Normalize triggers and extract signals.

Generate possible actions.

Rank candidates deterministically.

Select grounded evidence.

Build a MessagePlan.

Render the deterministic message first.

Optionally pass the already-decided message to the LLM composer.

Validate structure, facts, numbers, currency, CTA semantics, and grounding.

Use the deterministic message whenever composition is rejected.

The LLM is not responsible for choosing the business decision.

LLM / Model Choice

The decision engine is deterministic-first. Gemini is used only by the optional message-composition layer.

LLM decides the action?       No
LLM ranks candidates?         No
LLM selects evidence?         No
LLM may improve wording?      Yes, when explicitly enabled

This separation reduces hallucination risk and keeps business decisions reproducible.

The composer is disabled by default:

LLM_COMPOSER_ENABLED=false

It can be enabled for selected objectives through:

LLM_COMPOSER_OBJECTIVES=perf_dip,perf_spike,renewal_due,curious_ask_due

A provider failure, malformed response, unsupported fact, CTA mismatch, grounding failure, or other validation failure causes deterministic fallback.

Grounding

Generated used_facts are resolved against the actual structured context.

Examples of valid paths:

performance.delta_pct
merchant.offers[0].title

Unsupported or invented paths are rejected.

Numeric, percentage, currency, timing, offer, merchant-name, and CTA checks are preserved before an LLM response can replace the deterministic message.

API

Method

Endpoint

Purpose

GET

/v1/healthz

Health check

GET

/v1/metadata

Bot metadata

POST

/v1/context

Push versioned context

POST

/v1/tick

Generate actions

POST

/v1/reply

Process replies

The service listens on port 8080 by default and binds to 0.0.0.0 in container deployments.

Local Setup

Clone

git clone https://github.com/vamsikiran1234/Vera-message-engine.git
cd Vera-message-engine

Install

python -m venv .venv
python -m pip install -r requirements.txt

On Windows PowerShell:

.venv\Scripts\Activate.ps1

Run

python -m uvicorn bot:app --host 0.0.0.0 --port 8080

Health check:

http://localhost:8080/v1/healthz

PowerShell:

Invoke-RestMethod http://localhost:8080/v1/healthz

Testing

Focused composer tests:

python -m unittest tests.test_composer -q

Full suite:

python -m unittest discover -s tests -q

Compilation:

python -m compileall -q bot.py vera_engine tests

Diff hygiene:

git diff --check

Dataset generation:

python dataset/generate_dataset.py --seed-dir dataset --out expanded

Docker

Build:

docker build -t vera-message-engine .

Run:

docker run --rm -p 8080:8080 vera-message-engine

The container listens on 0.0.0.0:8080.

For public hosting, configure the platform to expose HTTPS and use /v1/healthz as the health endpoint.

Deployment

The project is container-ready for managed services such as Google Cloud Run.

A public deployment should provide:

HTTPS

automatic container restarts

environment-variable / secret management

the configured PORT

/v1/healthz health checking

a stable public base URL

The challenge runtime currently uses in-memory state for simplicity and low latency. A production system would use durable managed storage if restart-safe state were required.

Tradeoffs

Deterministic decision engine

Benefit: reproducible decisions and strong grounding.

Tradeoff: less flexible than a fully autonomous agent.

Deterministic rendering

Benefit: predictable output and reliable fallback.

Tradeoff: wording can be less natural than an LLM-generated message.

Optional LLM composition

Benefit: allows controlled wording improvements without giving the model decision authority.

Tradeoff: model availability, malformed responses, rate limits, and validation failures can cause fallback.

In-memory state

Benefit: simple and fast for the challenge.

Tradeoff: state is lost when the process restarts.

Strict validation

Benefit: prevents unsupported claims and unsafe rewrites.

Tradeoff: some fluent but unverifiable LLM responses are intentionally rejected.

Project Structure

Vera-message-engine/
├── bot.py
├── vera_engine/
│   ├── engine.py
│   ├── composer.py
│   ├── planner.py
│   ├── candidates.py
│   ├── scoring.py
│   ├── templates.py
│   ├── validator.py
│   ├── signals.py
│   └── store.py
├── dataset/
├── tests/
├── examples/
├── docs/
├── Dockerfile
├── requirements.txt
├── .env.example
└── judge_simulator.py

Reliability Strategy

The engine follows a fail-safe hierarchy:

1. Never invent facts.
2. Never let wording generation change the selected decision.
3. Prefer one strong CTA.
4. Ground messages in actual merchant context.
5. Reject unsupported LLM output.
6. Always retain deterministic fallback.

Challenge Submission

The deployed service must expose:

GET  /v1/healthz
GET  /v1/metadata
POST /v1/context
POST /v1/tick
POST /v1/reply

The local judge simulator is used for regression testing. The official evaluation can introduce fresh contexts and scenarios, so the engine is designed to operate from received context rather than hard-coded canonical examples.

Status

Challenge-ready

FastAPI API

Versioned context handling

Deterministic candidate selection

Grounded evidence selection

Message planning and templates

Optional guarded Gemini composition

Strict validation and fallback

Automated tests

Docker support

Public deployment ready

Author

Vamsi Kiran

Repository: https://github.com/vamsikiran1234/Vera-message-engine