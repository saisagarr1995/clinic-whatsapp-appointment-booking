# CLAUDE.md — read this first, every session

This file is loaded automatically at the start of every Claude Code session.

## MANDATORY session start procedure

Before doing ANY work in this repository, in this order:

1. Read `docs/SESSION_STATE.md` — where the last session stopped, what is in flight,
   what the next action is.
2. Read `docs/PROJECT_PLAN.md` — the locked plan. **Development must strictly follow it.**
3. Run `git status` and `git branch --show-current` to confirm the working branch.
4. Read the last 20 lines of `docs/PROGRESS.md` for recent build history.

Do not begin implementing until those four steps are done. Do not re-plan work that
`PROJECT_PLAN.md` has already decided — §2 of that file lists decisions that are locked
and must not be re-litigated.

## MANDATORY session end procedure

Before the session ends, or after completing any meaningful unit of work:

1. Update `docs/SESSION_STATE.md` — current branch, what was completed, what is in
   flight, the exact next action, and any blockers.
2. Append to `docs/PROGRESS.md` — dated entry describing what was built and why.
3. If the plan changed at all, update `docs/PROJECT_PLAN.md` **and**
   `RECREATE_PROMPT.md` in the same commit. These three must never drift apart.

## Project rules — non-negotiable

- **No AI/LLM at runtime.** This bot is a deterministic finite state machine. AI cost
  must remain exactly zero. Never add an AI SDK, an inference call, or an API key for one.
- **Open source only.** Every dependency must be MIT / Apache-2.0 / BSD. Every package
  must already be listed in `PROJECT_PLAN.md` §4. If a new package is genuinely needed,
  add it to §4 with a justification first, then install it.
- **Never install a package "to try it".** The plan exists so experimentation is unnecessary.
- **Never work on `main`.** Never work directly on `release/1.0` either. Cut
  `feature/CAB-XXXX` from `release/1.0`. Merge path is strictly
  `feature/CAB-XXXX → release/1.0 → main`.
- **Never commit secrets.** `.env`, `*.db`, and `RECREATE_PROMPT.md` are gitignored and
  must stay that way.
- **Clinic-specific data belongs in `config/clinic.yaml`**, never hardcoded in Python.
  Onboarding a new clinic must require zero code changes.
- **All user-facing strings live in `src/clinic_bot/whatsapp/messages.py`**, never inline
  in handlers — this keeps future translation a data-only change.

## Environment

- Python 3.12, venv at `.venv/` (Windows: `.venv\Scripts\python.exe`).
- Run commands through the venv interpreter, not bare `python`.
- Tests: `.venv\Scripts\python.exe -m pytest`
- Lint: `.venv\Scripts\python.exe -m ruff check src tests`
- Local run: `.venv\Scripts\python.exe -m uvicorn clinic_bot.main:app --reload --port 8000`

## Skills

`.claude/skills/` contains project skills. Invoke `project-context` at session start if
you want the full bootstrap read automatically.
