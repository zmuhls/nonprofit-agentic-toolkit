# Testing practice — simulated runs

`simulate.py` is the prototype's test practice: it replays **scripted user runs** against the live app and checks the invariants each stage is supposed to hold.

It simulates the browser by calling the **same `/api/chat` endpoint, in the same order, with the same payload shape** the page sends — `onboard` (the adaptive interview), `estimate` (the projection after Core 1), and `assistant` (Stage 2). No headless browser is needed; the request sequence *is* the run.

## Run

```bash
# 1. start the server in one terminal (key in env)
export OLLAMA_API_KEY="…"; python3 server.py

# 2. run the simulation in another
python3 tests/simulate.py              # all personas
python3 tests/simulate.py --persona maple
python3 tests/simulate.py --verbose    # fuller model replies
```

Exit code is `0` when every check passes, `1` otherwise — so it drops into CI or a pre-demo check unchanged.

The harness sends the server's access code on every call (`X-Access-Code`), defaulting to `AI4Wut`. If you start the server with a custom `ACCESS_CODE`, run the harness with the same value: `ACCESS_CODE=… python3 tests/simulate.py`.

There is also a key-free unit test for the reasoning-token strip — no server or key needed:

```bash
python3 tests/test_strip.py
```

## What a persona exercises

Each persona is one org: a free-write plus a bank of interview answers, plus a few Stage-2 task probes. One run walks the whole sequence:

`free-write → adaptive interview → routing → estimate → Stage-2 tasks`

## What it checks

| Stage | Invariant |
|---|---|
| Interview | each turn returns content; **one question, not a batch** (regression guard against the old 3-at-once); the loop **reaches a routing** recommendation that **names a stage** |
| Estimate | output has both a **`your sequence`** and a **`broader set`** section, and carries **effort markers** (session / weeks / ongoing) |
| Stage 2 — draft | a drafting task returns an answer (the assistant handles more than service lookup) |
| Stage 2 — PII | a message containing fake PII triggers a **warning to remove identifying details** |
| Stage 2 — scope | for an org with a service list, an out-of-directory question is **flagged as not in the directory** |
| Stage 2 — all | **no Fortune leakage** for a non-Fortune org (guards the org-agnostic rewrite) |
| Every stage | **no leaked reasoning tokens** — no `<think>` / `◁think▷` markers survive into content (guards the `strip_reasoning` fix) |

Because the model is live, replies vary run to run, so the checks are **keyword-tolerant**, not exact-match. A failure means the behavior drifted, not that the wording changed.

## Adding a persona

Append a dict to `PERSONAS` in `simulate.py`:

```python
{
  "id": "shortname", "org": "Org Name", "services": "- service one\n- service two",  # "" for no directory
  "freewrite": "what they'd type in the box…",
  "answers": ["answer to Q1", "answer to Q2", "answer to Q3"],   # consumed in order
  "stage2": [("draft", "a task…"), ("pii", "…SSN 123-45-6789…"), ("scope", "a service you don't offer?")],
}
```

The personas are deliberately **not Fortune** (Maple food pantry, Harbor legal aid) so every run also proves the toolkit serves a range of orgs, not one hardcoded case.

## Driving the real browser (optional)

This harness covers the request flow. To drive the actual UI (type into the box, click through, watch it render), a Playwright script can hit the same `http://127.0.0.1:8765`. Ask if you want that added — it's slower and flakier against a live model, which is why the request-replay harness is the default practice.
