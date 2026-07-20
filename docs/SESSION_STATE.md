# SESSION STATE — cross-session context handoff

> **Claude updates this at the end of every session and reads it at the start of every
> session.** If this file and reality disagree, trust `git status` and fix this file first.

---

## Snapshot

| Field | Value |
|-------|-------|
| Last updated | 2026-07-20 |
| Current phase | Core product complete; deployment not yet performed |
| Current branch | `release/1.0` |
| Repository | https://github.com/saisagarr1995/clinic-whatsapp-appointment-booking |
| Overall status | 🟢 Code complete and verified locally · 🟡 Never run against real WhatsApp |
| Blockers | Meta credentials and the Oracle VM do not exist yet — both need the user |

### Verification at last commit
```
pytest      152 passed
ruff        All checks passed
bandit      0 high, 0 medium
pip-audit   No known vulnerabilities found
```

---

## Completed

- [x] Requirements captured; 6 architectural questions resolved with the user
- [x] `PROJECT_PLAN.md` written and locked (14 decisions recorded)
- [x] Scaffolding, venv, dependency manifest — every package justified
- [x] Clinic config loader with strict operator-focused validation
- [x] DB models with partial unique index preventing double booking
- [x] Idempotent YAML→SQLite seeder
- [x] Transport abstraction + Cloud API adapter + recording fake
- [x] Availability engine: breaks, closing time, min notice, multi-slot services
- [x] Full FSM: welcome, services, contact, book new, reschedule, cancel, payment
- [x] UPI QR, payment page with app intents, I've Paid / Need Help
- [x] 152 tests; 5 bugs found and fixed (see `PROGRESS.md`)
- [x] Fleet infrastructure: systemd template, Caddy, `clinic-fleet`, backups
- [x] Docs: PLAN, PROGRESS, DEPLOYMENT, TWO_PHONE_TEST, SECURITY, README
- [x] `.claude` skills: project-context, session-handoff, whatsapp-flow, git-workflow, testing
- [x] GitHub repo created (public), `main` + `release/1.0` protected, verified by a
      rejected direct push. Secret scanning, push protection and Dependabot enabled.

## In flight

- [ ] Nothing mid-edit. The tree is clean.

## Next action (start here)

**The next step belongs to the user, not to Claude.** The product cannot progress further
without real infrastructure. In order:

1. Create the Oracle Cloud Always Free VM — `docs/DEPLOYMENT.md` Part 1.
2. Set up a DuckDNS subdomain — Part 2.
3. Run `deploy/install_server.sh` — Part 3.
4. Create the Meta app and get credentials — Part 4.
5. Work through `docs/TWO_PHONE_TEST.md` on both handsets.

When the user reports results from step 5, fix whatever it surfaces. **Until then, nothing
in this project has been proven against real WhatsApp** — only against the test suite.

### Remaining planned work (not blocking the above)

| ID | Scope | Status |
|----|-------|--------|
| CAB-0011 | One-command clinic onboarding wizard (`setup.py`, PLAN §10) | ⬜ not started |
| CAB-0012 | GitHub Actions auto-deploy on merge to main | ⬜ not started |

CAB-0011 matters commercially: today a clinic is onboarded by hand-editing `clinic.yaml`
and `.env`. The plan calls for an interactive wizard that validates Meta credentials live
and prints the exact webhook settings. Build it once the first clinic is running, so the
wizard reflects what the process actually turned out to be.

---

## Build sequence tracker

| ID | Scope | Status |
|----|-------|--------|
| CAB-0001 | Scaffolding, config, docs, skills | ✅ done |
| CAB-0002 | DB models, seeder | ✅ done |
| CAB-0003 | Transport + webhook | ✅ done |
| CAB-0004 | FSM + session store | ✅ done |
| CAB-0005 | Welcome / Services / Contact | ✅ done |
| CAB-0006 | Book New end-to-end | ✅ done |
| CAB-0007 | Reschedule + Cancel | ✅ done |
| CAB-0008 | UPI QR + payment page | ✅ done |
| CAB-0009 | Test suite + bug-fix pass | ✅ done |
| CAB-0010 | CI + branch protection | ✅ done |
| CAB-0011 | Onboarding wizard | ⬜ not started |
| CAB-0012 | Fleet deployment infrastructure | ✅ done (auto-deploy pipeline outstanding) |

---

## Open items needing the user

1. **Oracle Cloud account** — card needed for identity verification only, never charged.
   User confirmed they can do this.
2. **DuckDNS subdomain** — free, no card.
3. **Meta app per clinic** — phone number ID, business account ID, permanent access token,
   app secret. `docs/DEPLOYMENT.md` Part 4 has the click path.
4. **Phone B whitelisted** as a Meta test recipient (max 5).
5. **Real clinic data** for `clinic.yaml` — services, fees, doctors, hours, UPI ID.
   Placeholder data ships today.
6. **Phone A migration** off the WhatsApp mobile app — go-live only. ⚠️ This **erases the
   clinic's existing WhatsApp chat history**. Warn them; consider a fresh SIM instead.

---

## Decisions already made — do not re-ask

- WhatsApp transport: **Meta official Cloud API**. Reverse-engineered libraries were
  rejected — ToS violation, ban risk, unreliable button rendering.
- No `pywa`, no `alembic` — both dropped with reasons in `PROJECT_PLAN.md` §4.
- UPI: QR + copyable VPA + self-hosted payment page with app intents.
- Onboarding: `config/clinic.yaml` + SQLite seed, zero code changes per clinic.
- Hosting: **Oracle Cloud Always Free**. Sleeping/expiring free tiers rejected as unsellable.
- Database: **SQLite only**, no Postgres — a persistent disk removes the reason for it.
- Multi-clinic: **process + database per clinic**, not shared-database multi-tenancy,
  because a missing `WHERE clinic_id` would leak patient data between clinics.
- Routing: path-based `/c/<slug>/` so one certificate covers the fleet.
- Admin dashboard: deferred out of 1.0.

---

## Things a future session must not get wrong

- **Never use `datetime.now` as a SQLAlchemy column default or `onupdate`.** Always
  `clock.now()`. This caused BUG-001 and would have expired every patient session in
  production. See `PROGRESS.md`.
- **Never send an unprompted WhatsApp message.** Template messages are paid and would
  break the ₹0 guarantee. This is why reminders are deferred.
- **Button and row ids are a wire protocol.** A patient may tap a button from a message
  sent days ago. Never change an existing id value; only add.
- **Backups live on the same VM as the data.** Once there are paying clinics, they must be
  copied off-server. Documented in `DEPLOYMENT.md` but not yet implemented.

---

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-07-20 | Requirements gathered; plan locked; full product built and tested (152 tests); 5 bugs found and fixed; infrastructure redesigned twice as the user clarified hosting constraints and the 50-clinic scale target; GitHub repo created and protected. Nothing yet verified against real WhatsApp. |
