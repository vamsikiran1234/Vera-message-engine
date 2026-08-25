# Vera Message Engine

Vera is a deterministic, context-grounded merchant-growth message engine for the magicpin AI Challenge. It receives category, merchant, trigger, and optional customer contexts, selects a useful action, and returns one grounded message with one primary CTA.

## Architecture

```text
HTTP API
  -> versioned context store
  -> signal extraction
  -> candidate generation
  -> deterministic scoring and selection
  -> suppression
  -> message planning and templates
  -> grounding and safety validation
  -> JSON response
```

The core implementation is in `vera_engine/`. The API entrypoint is `bot.py`. The current runtime uses in-memory state for low latency and challenge execution.

## Endpoints

```text
GET  /v1/healthz
GET  /v1/metadata
POST /v1/context
POST /v1/tick
POST /v1/reply
```

The implementation follows the schemas in the provided challenge briefs. Context pushes are versioned; higher versions replace older versions and stale versions return HTTP 409.

## Run Locally

```powershell
python -m pip install -r requirements.txt
python -m uvicorn bot:app --host 0.0.0.0 --port 8080
```

Check health:

```powershell
Invoke-RestMethod http://localhost:8080/v1/healthz
```

## Test

```powershell
python -m unittest discover -s tests -q
python -m compileall -q bot.py vera_engine tests
python dataset/generate_dataset.py --seed-dir dataset --out expanded
```

The local judge requires an LLM provider for scoring. See `docs/judge-setup.md` for secret-safe Gemini or Groq configuration.

## Environment

The bot accepts `PORT`, `TEAM_NAME`, `TEAM_MEMBERS`, `CONTACT_EMAIL`, `VERSION`, and `SUBMITTED_AT`. The judge uses the provider settings documented in `.env.example`. Never commit `.env` or API keys.

## Deployment

Build and run the included container:

```powershell
docker build -t vera-message-engine .
docker run --rm -p 8080:8080 vera-message-engine
```

For a public deployment, expose the container through one HTTPS base URL and configure the platform health check as `/v1/healthz`. The service listens on `0.0.0.0` and uses port `8080` by default.

## Tradeoffs

- Deterministic templates are used instead of an LLM in the bot path to reduce hallucination and latency.
- In-memory state is suitable for the challenge process but should be replaced by SQLite or managed storage for restart-safe production use.
- Generated placeholder triggers are handled conservatively; unsupported facts are omitted rather than invented.
- The local simulator is an evaluation aid and does not reproduce every behavior of the official harness.
