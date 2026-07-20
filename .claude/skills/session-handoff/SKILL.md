---
name: session-handoff
description: Write the end-of-session handoff so the next session resumes cleanly. Use when wrapping up, when the user says they are stopping, closing, or done for now, or after finishing a feature branch. Updates SESSION_STATE.md, PROGRESS.md and, when the plan changed, PROJECT_PLAN.md and RECREATE_PROMPT.md together.
---

# Write the session handoff

The user starts every session fresh. Everything not written down is lost.

## 1. Update `docs/SESSION_STATE.md`

Rewrite these sections to match reality — do not append, replace:

- **Snapshot** — last updated date, current phase, current branch, overall status, blockers
- **Completed** — move finished items out of "In flight"
- **In flight** — what is genuinely half-done, with enough detail to resume
- **Next action** — a single concrete instruction, not a vague direction.
  Good: "Write `tests/test_setup_wizard.py`, then run the full suite."
  Bad: "Continue with testing."
- **Build sequence tracker** — update the ⬜/🟡/✅/🔴 status column
- **Open items needing the user** — anything blocked on their credentials or decisions
- **Session log** — append one dated row

## 2. Append to `docs/PROGRESS.md`

A dated entry covering:
- what was built and **why** — the reasoning, not just the file list
- any bug found, its root cause, and the fix (these are the most valuable entries)
- anything deliberately deferred, and what triggers picking it up

## 3. If the plan changed

`PROJECT_PLAN.md`, `PROGRESS.md` and `RECREATE_PROMPT.md` must never drift apart. If any
decision, dependency, branch or scope item changed:

- update the relevant section of `PROJECT_PLAN.md`
- add a row to its change log with the date and reason
- update `RECREATE_PROMPT.md` so the single-prompt rebuild still produces this project
- commit all of them together

## 4. Verify before finishing

```bash
pytest -q                  # must be green
git status --short         # nothing unintended staged
```

Never hand off a red suite without saying so explicitly in `SESSION_STATE.md` under
Blockers, including which tests fail and why.

## 5. Tell the user

Two or three lines: what got done, what is next, what you need from them.
