# Vera Project Structure

The repository keeps the challenge contract, engine code, tests, generated fixtures, and assistant-created documentation separate.

```text
magicpin-ai-challenge/
|-- bot.py                         FastAPI entrypoint and official routes
|-- requirements.txt               Runtime dependencies
|-- challenge-brief.md             Provided product/challenge brief
|-- challenge-testing-brief.md     Provided HTTP and judge contract
|-- engagement-design.md           Provided engagement proposal
|-- engagement-research.md         Provided research notes
|-- judge_simulator.py             Provided local judge simulator
|-- dataset/                       Provided seed data and generator
|-- expanded/                      Generated evaluation fixtures
|-- examples/                      Provided API examples and case studies
|-- vera_engine/                   Reusable application and domain logic
|   |-- models.py                  Typed context and API models
|   |-- store.py                   Versioned context and conversation state
|   |-- signals.py                 Trigger normalization and signal extraction
|   |-- candidates.py              Candidate action generation
|   |-- scoring.py                 Deterministic candidate scoring
|   `-- selection.py               Suppression and action selection
|-- tests/                         Unit and API tests
`-- docs/                          Documentation created during implementation
    |-- technical-design.md        Phase 3 technical design
    `-- project-structure.md       This structure guide
```

## Ownership Rules

- Provided challenge files remain in their original locations.
- Generated dataset files remain under `expanded/` and are not hand-edited.
- Runtime code belongs in `bot.py` or `vera_engine/`.
- Tests belong in `tests/` and mirror the engine module they cover.
- New assistant-created Markdown documents belong in `docs/`.

The package is intentionally flat while the engine is small. New subpackages should be introduced only when a module group has a distinct ownership boundary and the move can preserve stable imports.