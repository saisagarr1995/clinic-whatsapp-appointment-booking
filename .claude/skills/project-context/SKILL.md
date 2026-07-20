---
name: project-context
description: Load full project context at the start of a session. Use this FIRST in any new session before touching the clinic WhatsApp booking codebase — it reads the plan, the session state and the build progress so work continues correctly instead of restarting. Triggers on "what were we doing", "continue", "resume", "catch up", or the start of any work in this repo.
---

# Load project context

Run this before any other work in this repository. It exists because the user works in
short sessions and expects a new session to pick up exactly where the last one stopped.

## Step 1 — Read the state files, in this order

1. `docs/SESSION_STATE.md` — **the handoff.** Current phase, current branch, what is in
   flight, the exact next action, and open blockers.
2. `docs/PROJECT_PLAN.md` — **the locked plan.** Pay attention to §2 (decisions that must
   not be re-litigated) and §6 (the branch build sequence).
3. `docs/PROGRESS.md` — last ~30 lines, for recent history and any bugs already found.

## Step 2 — Verify reality against the files

```bash
git branch --show-current
git status --short
git log --oneline -5
```

If `SESSION_STATE.md` disagrees with git, **git is right** — correct the file immediately
and say so. A stale handoff file is worse than none.

## Step 3 — Confirm the environment still works

```bash
.venv/Scripts/python.exe -m pytest -q       # Windows
.venv/bin/python -m pytest -q               # Linux
```

A red suite at session start means the previous session left something broken. Fix that
before starting anything new.

## Step 4 — Report back before acting

Tell the user, in a few lines:
- which phase and branch you are on
- what the last session completed
- the next action from the plan
- anything blocked and waiting on them

Then start work. Do not re-plan what is already decided.

## Rules that apply for the whole session

- **Follow `PROJECT_PLAN.md` strictly.** Deviating requires updating the plan,
  `PROGRESS.md` and `RECREATE_PROMPT.md` together, in the same commit.
- **No AI/LLM at runtime, ever.** Runtime AI cost must stay exactly ₹0.
- **Only packages listed in `PROJECT_PLAN.md` §4.** Add to the plan with a justification
  first, then install. Never install something "to try it".
- **Never work on `main` or `release/1.0`.** Cut `feature/CAB-XXXX` from `release/1.0`.
- **Never commit secrets.** `.env`, `*.db` and `RECREATE_PROMPT.md` stay gitignored.
- **Clinic data lives in `config/clinic.yaml`**, never hardcoded.
- **Patient-visible copy lives in `whatsapp/messages.py`**, never inline in handlers.

## Before the session ends

Update `docs/SESSION_STATE.md` and append to `docs/PROGRESS.md`. This is not optional —
the next session depends entirely on it.
