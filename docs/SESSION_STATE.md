# SESSION STATE — cross-session context handoff

> Machine-and-human readable handoff. **Claude updates this at the end of every session
> and reads it at the start of every session.** If this file and reality disagree, trust
> `git status` and fix this file immediately.

---

## Snapshot

| Field | Value |
|-------|-------|
| Last updated | 2026-07-20 |
| Current phase | CAB-0001 — scaffolding & planning |
| Current branch | *(not yet a git repo — init pending)* |
| Release branch | `release/1.0` |
| Overall status | 🟡 In progress — plan locked, implementation starting |
| Blockers | Meta Cloud API credentials not yet provisioned by the user (see below) |

---

## Completed

- [x] Requirements captured and ambiguities resolved with the user
- [x] Transport decision locked: Meta Cloud API via open-source `pywa` (PROJECT_PLAN §2 D1)
- [x] Folder structure created
- [x] Python 3.12 venv created at `.venv/`
- [x] `docs/PROJECT_PLAN.md` written and locked
- [x] `CLAUDE.md` session bootstrap written

## In flight

- [ ] CAB-0001 — remaining scaffolding: `pyproject.toml`, `settings.py`, `clinic.yaml`,
      `.claude` skills, `PROGRESS.md`, `RECREATE_PROMPT.md`, `.gitignore`

## Next action (start here)

Finish CAB-0001 scaffolding, then proceed to CAB-0002 (DB models + YAML seeder) exactly as
sequenced in `PROJECT_PLAN.md` §6. Do not skip ahead or reorder branches.

---

## Build sequence tracker

| ID | Scope | Status |
|----|-------|--------|
| CAB-0001 | Scaffolding, config, docs, skills | 🟡 in progress |
| CAB-0002 | DB models, migrations, YAML seeder | ⬜ not started |
| CAB-0003 | Transport abstraction + Cloud API adapter + webhook | ⬜ not started |
| CAB-0004 | FSM core + persisted session store | ⬜ not started |
| CAB-0005 | Welcome / Our Services / Contact Us | ⬜ not started |
| CAB-0006 | Book New end-to-end | ⬜ not started |
| CAB-0007 | Reschedule + Cancel | ⬜ not started |
| CAB-0008 | UPI QR + payment page | ⬜ not started |
| CAB-0009 | Full test suite + auto bug-fix pass | ⬜ not started |
| CAB-0010 | CI + GitHub branch protection | ⬜ not started |

Legend: ⬜ not started · 🟡 in progress · ✅ done · 🔴 blocked

---

## Open items needing the user

These block **go-live**, not development. Development and testing proceed with fakes and
the Meta test number.

1. **Meta Cloud API credentials.** Needed in `.env`:
   `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID`, `WHATSAPP_ACCESS_TOKEN`,
   `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`.
   Obtained from developers.facebook.com → create Business app → add WhatsApp product.
   `docs/SETUP.md` carries the click-by-click walkthrough.
2. **Phone B whitelisted** as a test recipient in the Meta dashboard (max 5 allowed).
3. **Real clinic data** for `config/clinic.yaml` — services, fees, doctors, working hours,
   UPI ID and UPI display name. Placeholder data is in place until then.
4. **Phone A migration** off the WhatsApp mobile app — go-live only, not needed for testing.

---

## Decisions the user has already made (do not re-ask)

- WhatsApp transport: official Cloud API via `pywa`, because reverse-engineered libraries
  violate ToS and get numbers banned.
- UPI: QR image + UPI ID + self-hosted payment page with GPay/PhonePe/Paytm/CRED intents.
- Webhook exposure in dev: cloudflared quick tunnel.
- Clinic onboarding: `config/clinic.yaml` + SQLite seed.
- Admin dashboard: deferred out of 1.0.

---

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-07-20 | Requirements gathered, 4 architectural questions resolved, plan written and locked, scaffolding started. |
