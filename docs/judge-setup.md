# Local Judge Setup

The Vera bot itself does not require an API key. The local judge uses an LLM to score messages, so configure one provider locally.

## Groq

1. Create a Groq API key in the Groq developer console.
2. In PowerShell, set the key for the current terminal session:

```powershell
$env:LLM_PROVIDER = "groq"
$env:LLM_API_KEY = "paste-your-groq-key-here"
$env:LLM_MODEL = "llama-3.1-70b-versatile"
python judge_simulator.py
```

The key is read from the environment and is never written to the repository. Do not paste the real key into `.env.example`, `judge_simulator.py`, or any tracked file.

## Scenarios

Run a specific simulator scenario with:

```powershell
$env:TEST_SCENARIO = "phase2_short"
python judge_simulator.py
```

Available scenarios are listed in `judge_simulator.py` and include `warmup`, `phase2_short`, `auto_reply_hell`, `intent_transition`, `hostile`, `all`, and `full_evaluation`.

## Local-only `.env`

`.env` is ignored by Git. It contains blank placeholders initially. The simulator reads process environment variables directly; PowerShell assignments above are the most reliable setup and avoid storing secrets on disk.