# Local Judge Setup

The Vera bot itself does not require an API key. The local judge uses Gemini to score messages.

## Gemini

1. Obtain a Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Add it to your local `.env` file (never commit this file):

```text
LLM_PROVIDER=gemini
LLM_API_KEY=your-gemini-key-here
GEMINI_MODELS=gemini-3.5-flash-lite,gemini-3.1-flash-lite
```

3. Run the judge:

```powershell
python judge_simulator.py
```

The simulator tries the models in `GEMINI_MODELS` in order and falls back to the next if one is unavailable. `gemini-3.5-flash-lite` is the confirmed working primary model.

## Scenarios

Run a specific simulator scenario with:

```powershell
$env:TEST_SCENARIO = "phase2_short"
python judge_simulator.py
```

Available scenarios: `warmup`, `phase2_short`, `auto_reply_hell`, `intent_transition`, `hostile`, `all`, `full_evaluation`.

## Local-only `.env`

`.env` is ignored by Git. Never paste a real API key into `.env.example`, `judge_simulator.py`, or any tracked file.
