# SESSION STATE — cross-session context handoff

> **Claude updates this at the end of every session and reads it at the start of every
> session.** If this file and reality disagree, trust `git status` and fix this file first.

---

## Snapshot

| Field | Value |
|-------|-------|
| Last updated | 2026-07-26 |
| Current phase | Multi-clinic fleet complete incl. staff payment verification; never run against real WhatsApp |
| Current branch | `release/1.0` — CAB-0014/0015/0016 merged and promoted to `main` |
| Repository | https://github.com/saisagarr1995/clinic-whatsapp-appointment-booking |
| Overall status | 🟢 Fleet runs on the laptop and the full flow is proven in the simulator · 🟡 Never run against real WhatsApp |
| Blockers | Meta credentials do not exist yet — needs the user |

### Verification at last commit
```
pytest      202 passed
ruff        All checks passed
bandit      0 high, 0 medium
pip-audit   No known vulnerabilities found
memory      82.1 MB one clinic · 86.8 MB five clinics (measured RSS)
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
- [x] 202 tests; 7 bugs found and fixed (see `PROGRESS.md`)
- [x] Clinic fleet: `config/clinics.yaml` registry, one process, DB per clinic
- [x] Offline simulator, gated on `SIMULATOR` (default off)
- [x] **Staff payment verification** — UTR capture + `payments`/`confirm`/`reject`
- [x] Docs: PLAN, PROGRESS, LOCAL_HOSTING, TWO_PHONE_TEST, SECURITY, README
- [x] `.claude` skills: project-context, session-handoff, whatsapp-flow, git-workflow, testing
- [x] GitHub repo created (public), `main` + `release/1.0` protected, verified by a
      rejected direct push. Secret scanning, push protection and Dependabot enabled.

## In flight

- [ ] Nothing mid-edit. CAB-0014 is complete and committed; the tree is clean.

## Next action (start here)

The bot **runs on the user's laptop right now** and the whole conversation has been
validated in the offline simulator. Hosting no longer blocks progress; only Meta does.

To go live, in order — all documented in `docs/LOCAL_HOSTING.md`:

1. Install Tailscale, enable MagicDNS + HTTPS, run `tailscale funnel 8000`.
2. Put the `https://….ts.net` address in `.env` as `PUBLIC_BASE_URL`.
3. **Set `SIMULATOR=false`** before the address is public. The simulator accepts
   unsigned messages by design.
4. Create a Meta app per clinic, fill `config/secrets/<slug>.env`.
5. `python scripts/clinic_admin.py webhook <slug>` prints exactly what to paste.
6. Work through `docs/TWO_PHONE_TEST.md`.

**Nothing in this project has yet been proven against real WhatsApp** — only against
the test suite and the simulator. Message delivery, button rendering on a handset and
UPI apps opening are all still unverified.

## Resolved on 2026-07-26 (CAB-0015)

The process-per-clinic deploy assets that contradicted D13 were **deleted**, not
patched: `deploy/fleet.sh`, `deploy/clinic-bot@.service`, `deploy/clinic-bot.target`,
`deploy/install_server.sh` and `docs/DEPLOYMENT.md`. They are recoverable from git
history (commit `ffdf1fe`).

`deploy/Caddyfile` survives and is correct for the single-process fleet. **If the
Oracle VM path is ever revived, the systemd unit must be written fresh as ONE unit
for the whole fleet**, not a per-clinic template.

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
| CAB-0012 | Fleet deployment infrastructure | ✅ done (auto-deploy outstanding; superseded in part by CAB-0014) |
| CAB-0013 | Session handoff after initial build | ✅ done |
| CAB-0014 | Laptop hosting, clinic registry, simulator, QR removal | ✅ done |
| CAB-0015 | Payment verification, timezone fix, dead-code removal | ✅ done |
| CAB-0016 | Post-release tidy: stray screenshot, documented required checks | ✅ done |

---

## Open items needing the user

1. **Tailscale account + Funnel** — free, no card, no domain. Gives the stable public
   HTTPS address the Meta webhook needs. `docs/LOCAL_HOSTING.md` §3.
2. **Meta app per clinic** — phone number ID, permanent access token, app secret,
   verify token, into `config/secrets/<slug>.env`. `LOCAL_HOSTING.md` §4.
3. **Phone B whitelisted** as a Meta test recipient (max 5).
4. **Real clinic data** for `config/clinic.yaml` — services, fees, doctors, hours,
   UPI ID. Placeholder data ships today.
5. **Power settings** — the laptop must not sleep or the whole fleet goes offline.
   Commands are printed by `scripts/install_autostart.ps1`; the user must run them.
6. **Phone A migration** off the WhatsApp mobile app — go-live only. ⚠️ This **erases the
   clinic's existing WhatsApp chat history**. Warn them; consider a fresh SIM instead.
7. **Oracle Cloud VM** — no longer blocking, but still the right host for clinics with
   real patients. Deferred by the user in favour of laptop hosting.

---

## Decisions already made — do not re-ask

- WhatsApp transport: **Meta official Cloud API**. Reverse-engineered libraries were
  rejected — ToS violation, ban risk, unreliable button rendering.
- No `pywa`, no `alembic` — both dropped with reasons in `PROJECT_PLAN.md` §4.
- UPI: copyable VPA + self-hosted payment page with app intents. **No QR** — removed
  2026-07-26, which also removed Pillow. See `PROJECT_PLAN.md` D4.
- Onboarding: `config/clinics.yaml` registry + per-clinic YAML + SQLite seed. Zero code
  changes per clinic.
- Hosting: **the user's laptop**, via Tailscale Funnel (chosen 2026-07-26). Oracle Cloud
  Always Free remains the recommendation for real patient load, not a blocker.
- Database: **SQLite only**, no Postgres — a persistent disk removes the reason for it.
- Multi-clinic: **one process, one database per clinic** (amended 2026-07-26 from
  process-per-clinic, for laptop memory). No shared tables, no `WHERE clinic_id`.
- Routing: path-based `/c/<slug>/` so one certificate covers the fleet.
- Simulator: gated on `SIMULATOR`, default **false**. Never on in production.
- Payment verification: **a human at the clinic**, via `clinic_admin.py confirm/reject`.
  No gateway, no auto-reconciliation. Unverified claims are NOT auto-expired.
- Admin dashboard: deferred out of 1.0. The staff CLI is the 1.0 answer.

---

## Things a future session must not get wrong

- **Never use `datetime.now` as a SQLAlchemy column default or `onupdate`.** Always
  `clock.now()`. This caused BUG-001 and would have expired every patient session in
  production. See `PROGRESS.md`.
- **Never send an unprompted WhatsApp message.** Template messages are paid and would
  break the ₹0 guarantee. This is why reminders are deferred.
- **Button and row ids are a wire protocol.** A patient may tap a button from a message
  sent days ago. Never change an existing id value; only add.
- **Backups live on the same machine as the data.** Once there are paying clinics, they
  must be copied off the laptop. `LOCAL_HOSTING.md` §5 gives the command; it is not
  automated.
- **`SIMULATOR=true` must never reach a public deployment.** `/c/<slug>/sim` injects
  messages into the state machine with no webhook signature — exactly what
  `verify_signature` exists to prevent. It defaults to false and the routes are not
  registered when off; keep it that way.
- **The clinic slug is a wire protocol too.** It is in the webhook URL registered with
  Meta and in payment links already sitting in patients' chats. Never rename a slug.
- **Cross-clinic isolation is proven by test, not by the OS**, since D13 was amended.
  `tests/test_multi_clinic.py` is load-bearing — if it is ever weakened, revisit D13.
- **`CONFIRMED` may only ever be set by `booking_service.confirm_booking`.** The bot
  cannot see money move; if any patient-reachable path sets it, the clinic starts
  giving away appointments for free. Guarded by `tests/test_payment_verification.py`.
- **The bot must never tell a patient their payment is confirmed** — only that it is
  being verified. A test asserts the exact phrases are absent.
- **Never catch bare `Exception` around timezone or config lookups.** BUG-007 hid a
  missing IANA database behind a blanket `except` for two sessions, silently computing
  every appointment in the wrong timezone. Catch the specific error and log loudly.

---

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-07-20 | Requirements gathered; plan locked; full product built and tested (152 tests); 5 bugs found and fixed; infrastructure redesigned twice as the user clarified hosting constraints and the 50-clinic scale target; GitHub repo created and protected. Nothing yet verified against real WhatsApp. |
| 2026-07-26 | **CAB-0015.** User asked how the clinic would know a patient had really paid, and for a correctness + dead-code pass. Found `CONFIRMED` was unreachable and a false "I've Paid" held a slot forever with no staff tool (BUG-006), and that a blanket `except Exception` was hiding a missing IANA timezone database on Windows so every appointment used machine-local time (BUG-007). Added UTR capture, `payments`/`confirm`/`reject` staff commands, `tzdata` + timezone validation, and a fleet mixed-timezone guard. Removed `ImageMessage`, dead `Settings` members and the superseded process-per-clinic deploy assets. 180 → 202 tests. Server stopped at the user's request. |
| 2026-07-26 | **CAB-0014.** User moved hosting to their laptop and asked for a multi-clinic fleet driven by one registry file, plus lower memory and no QR. Built `config/clinics.yaml` + `registry.py`; refactored three global singletons to be per-clinic; path-scoped every route to `/c/<slug>/`; per-clinic Meta credentials and signature verification. Removed the UPI QR and with it Pillow. Added a gated offline simulator, the `clinic_admin` CLI, Windows run/autostart scripts, CodeQL and Dependabot. 152 → 180 tests. Measured 82 MB for one clinic, 87 MB for five. Full booking driven end to end through the simulator. Still unverified against real WhatsApp. |
