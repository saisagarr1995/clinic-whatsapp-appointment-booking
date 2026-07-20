---
name: git-workflow
description: Branching, commit and merge rules for this repository. Use before creating any branch, committing, opening a PR, or merging — the repo has strict protection rules and a fixed feature/CAB-XXXX to release/1.0 to main promotion path that must not be bypassed.
---

# Git workflow

The repository is **public**. `main` being green means "this is live at customer clinics".
Protecting it is the whole point of these rules.

## The only permitted path

```
feature/CAB-XXXX  →  release/1.0  →  main
```

- **Never commit to `main`.** Direct pushes are blocked for everyone, admins included.
- **Never commit to `release/1.0`.** It only receives merges from feature branches.
- Every change starts as a feature branch cut from `release/1.0`.

## Branch naming

`feature/CAB-XXXX` — zero-padded to four digits, matching a row in `PROJECT_PLAN.md` §6.

```
feature/CAB-0006     ✅
feature/CAB-6        ❌
feature/booking-fix  ❌
```

For work not in the plan: add a row to §6 first, then use its id.

## Starting work

```bash
git checkout release/1.0
git pull origin release/1.0
git checkout -b feature/CAB-0006
```

## Commits

Present tense, explaining **why** where it is not obvious:

```
Add slot hold expiry sweeper

Abandoned bookings held slots indefinitely, so a patient who never paid
blocked that time for everyone. Holds now expire after booking.hold_minutes
and are swept on every inbound message.
```

Requirements:
- Tests pass before committing.
- `ruff check src tests` is clean.
- No secrets. `.env`, `*.db`, `RECREATE_PROMPT.md` are gitignored — keep it that way.
- If the plan changed, `PROJECT_PLAN.md`, `PROGRESS.md` and `RECREATE_PROMPT.md` are
  updated **in the same commit**.

## Opening a PR

```bash
git push -u origin feature/CAB-0006
gh pr create --base release/1.0 --title "CAB-0006: <what>" --body "<why>"
```

Base is **`release/1.0`**, never `main`. CI must be green before merging.

## Promoting to production

Only when `release/1.0` is fully green and manually verified:

```bash
gh pr create --base main --head release/1.0 --title "Release 1.0.x"
```

Merging to `main` means the change is live. Treat it accordingly.

## Never do these

- `git push --force` to `main` or `release/1.0`
- `--no-verify` to skip hooks
- Committing `.env`, a `.db` file, or `RECREATE_PROMPT.md`
- Merging your own PR without CI passing
- Changing branch protection to make something merge

## If you committed a secret

Rotate the credential **first** — assume it is already compromised. Then clean history.
Never just delete the file in a later commit; it stays in history and the repo is public.
