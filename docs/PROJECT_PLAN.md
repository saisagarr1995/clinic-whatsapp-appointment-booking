# Clinic WhatsApp Appointment Booking — Project Plan

> **This is the single source of truth.** Development must strictly follow this plan.
> Any deviation requires updating this file AND `docs/PROGRESS.md` AND `RECREATE_PROMPT.md`
> in the same commit.

- **Version:** 1.0
- **Created:** 2026-07-20
- **Last updated:** 2026-07-20
- **Release branch:** `release/1.0`

---

## 1. Product definition

A WhatsApp-native appointment booking bot for a dental clinic. A patient messages the
clinic's WhatsApp number and completes an entire booking — service selection, doctor,
date, time slot, confirmation and UPI payment — without a human replying and without any
AI/LLM inference.

**Commercial goal:** one-time setup per clinic. All clinic-specific data lives in
`config/clinic.yaml`. Zero code changes are required to onboard a new clinic.

### Non-goals (explicitly out of scope for 1.0)
- No AI, LLM, or NLP. The bot is a deterministic finite state machine. **AI cost = ₹0.**
- No payment gateway integration or automated payment reconciliation. Payment is UPI
  peer-to-peer; the patient self-declares via an "I've Paid" button and clinic staff verify.
- No admin web dashboard (deferred — see §9 Future work).
- No shared-database multi-tenancy. **One process + one database file per clinic**, with
  many clinics on one server. See §12.

### Scale target
50 clinics × 50 patients/day = 2,500 bookings and ~35,000 WhatsApp messages per day.
Average ~1 msg/sec, peak ~5 msg/sec, ~275 MB of data growth per year. One Oracle Always
Free VM (4 ARM cores, 24 GB RAM, 200 GB disk) carries this with large headroom; at 50
clinics the fleet uses roughly 5 GB of RAM. All 35,000 daily messages are replies to
patient-initiated conversations, so the WhatsApp cost remains ₹0 at full scale.

---

## 2. Decisions locked (do not re-litigate)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Meta WhatsApp Cloud API** as transport, via the open-source `pywa` client | Only option that is simultaneously ToS-compliant, ban-safe, supports interactive reply buttons + list messages, and free for user-initiated conversations. Reverse-engineered libraries (`neonize`, `whatsmeow`) violate WhatsApp ToS and get numbers banned — unacceptable for a product being sold. |
| D2 | **All project code and dependencies are open source** (MIT/Apache/BSD only) | User requirement. Verified per-package in §4. |
| D3 | **Python 3.12 + FastAPI + SQLAlchemy + SQLite** | Lean, no server dependencies, single-file DB suits a single clinic. |
| D4 | **UPI: QR image + UPI ID text + self-hosted payment page** | WhatsApp will not open a `upi://` deep link from chat text. A small page served by our own FastAPI app carries GPay/PhonePe/Paytm/CRED intent buttons. |
| D5 | **cloudflared quick tunnel** for local webhook exposure | Free, no account, no card. |
| D6 | **`config/clinic.yaml` + SQLite seed** for clinic onboarding | Matches the one-time-setup sellable goal. |
| D7 | **Transport abstraction layer** (`whatsapp/base.py`) | The bot core never imports `pywa` directly, so a second adapter can be added without touching flow logic. |
| D8 | **Session state persisted in SQLite**, not in memory | Bot must survive restarts mid-conversation. |
| D9 | **Oracle Cloud Always Free VM** as production host | The only genuinely free, always-on, production-grade option. Free forever (not a trial). Free hosts with ephemeral disks or idle-sleep were rejected: a bot that takes ~50s to answer the first message is not sellable to a clinic. |
| D10 | **SQLite only — no Postgres** | D9 gives a persistent disk, which removes the only reason to add Postgres. For one clinic (~50 bookings/day) SQLite is faster, has no second service to run or patch, and backs up by copying one file. Adding Postgres would be maintenance burden with no benefit, plus an extra dependency. |
| D11 | **Caddy + Let's Encrypt + DuckDNS** for HTTPS | Meta requires a valid HTTPS certificate on the webhook. Caddy obtains and renews one automatically, free. |
| D12 | **systemd** for process supervision | Auto-restart on crash and auto-start on reboot, with no extra dependency — it is already on the VM. |

### Nothing runs on the developer's laptop
The laptop writes code and pushes to GitHub. GitHub Actions deploys to the VM. The clinic's
bot is alive whether or not the laptop is switched on. `PUBLIC_BASE_URL` is the VM's
permanent DuckDNS HTTPS URL — the cloudflared tunnel (D5) is retained **only** as an
optional convenience for local flow testing, and is not part of the production path.

| D13 | **Process + database per clinic**, not shared-database multi-tenancy | Isolation is enforced by the OS rather than by a `WHERE clinic_id = ...` that a future change could omit. A single missed filter in a shared design would leak one clinic's patient medical data to another — unacceptable for health data in a product being sold. Also keeps the already-written, already-tested single-clinic code unchanged. |
| D14 | **Path-based routing** (`/c/<slug>/…`), not per-clinic subdomains | One TLS certificate, no wildcard-DNS complexity, and `PUBLIC_BASE_URL` simply carries the prefix — so no application code has to know about routing. |

### Recurring cost
₹0 infrastructure, ₹0 AI. The only cost is a domain if the clinic later wants a branded one.

### D1 consequence the clinic must action
The clinic's number (Phone A) **cannot** be registered in the WhatsApp mobile app and on
the Cloud API at the same time. Go-live requires migrating the number off the app.
During development, Meta's **free test number** (max 5 whitelisted recipients) is used, so
Phone B can be tested immediately without touching Phone A.

---

## 3. Conversation flow specification

This is the contract. Every state, trigger and transition below is implemented and tested
verbatim.

### 3.1 State machine

```
IDLE
 └─ any inbound text ────────────────────────────► WELCOME
     buttons: [Book Appointment] [Our Services] [Contact Us]

WELCOME
 ├─ "Our Services"  ──► SERVICES_LIST  (services + fee-from + clinic hours,
 │                                      followed by a message with [Book Appointment])
 ├─ "Contact Us"    ──► CONTACT        (clinic phone, address, hours) → [Book Appointment]
 └─ "Book Appointment" ──► BOOKING_MENU

BOOKING_MENU
     buttons: [Book New] [Reschedule] [Cancel]
 ├─ "Book New"    ──► ASK_NAME
 ├─ "Reschedule"  ──► RESCHEDULE_PICK_BOOKING
 └─ "Cancel"      ──► CANCEL_PICK_BOOKING

ASK_NAME
     sends: "Great! Let's get you booked in."
            "May I have your full name please?"
 └─ free text ──► ASK_SERVICE
     sends: "Thank you {name}!"
            "Which service do you need today?"  + [View Services] button

ASK_SERVICE
 └─ tap [View Services] ──► emits WhatsApp *list message* of services
 └─ list selection ──► PICK_DOCTOR

PICK_DOCTOR   list of doctors who provide the chosen service
 └─ selection ──► PICK_DATE

PICK_DATE     list of next N working dates for that doctor with free capacity
 └─ selection ──► PICK_SLOT

PICK_SLOT     list of unbooked time slots for (doctor, date)
 └─ selection ──► SUMMARY

SUMMARY       full booking summary
     buttons: [Confirm] [Change Details]
 ├─ "Change Details" ──► ASK_SERVICE   (name retained, booking draft reset)
 └─ "Confirm"        ──► PAYMENT
                          msg 1: confirmation + UPI ID + UPI name + QR image
                                 + link to payment page (app chooser)
                          msg 2: buttons [I've Paid] [Need Help]

PAYMENT
 ├─ "I've Paid"  ──► PAID     (thank-you/greeting, booking marked AWAITING_VERIFICATION)
 └─ "Need Help"  ──► HELP     (clinic mobile number) → [I've Paid]
```

### 3.2 Booking lifecycle

`DRAFT → PENDING_PAYMENT → AWAITING_VERIFICATION → CONFIRMED | CANCELLED | RESCHEDULED`

A slot is held (reserved) at `PENDING_PAYMENT` and auto-released after
`booking.hold_minutes` (default 15) if payment is not declared. Release is handled by a
background sweeper task, not a cron dependency.

### 3.3 Hard rules
- **No double booking.** `(doctor_id, starts_at)` carries a UNIQUE constraint at the DB
  level, not just an application check.
- Any inbound message matching a reset keyword (`hi`, `hello`, `menu`, `start`, `restart`)
  from any state returns to `WELCOME`.
- Unrecognised input in a state re-sends that state's prompt with a gentle nudge — the
  bot never dead-ends.
- Sessions expire after `session.timeout_minutes` (default 30) of inactivity.

---

## 4. Dependency manifest — every package justified

Nothing is installed that is not listed here.

### Runtime
| Package | License | Why it is required |
|---------|---------|--------------------|
| `fastapi` | MIT | Webhook endpoint + payment page. |
| `uvicorn[standard]` | BSD-3 | ASGI server. |
| `sqlalchemy` | MIT | ORM over SQLite. |
| `pydantic-settings` | MIT | Typed env/secret loading. |
| `pyyaml` | MIT | Parse `clinic.yaml`. |
| `qrcode[pil]` | BSD-3 | Generate the UPI QR locally (no third-party QR service = no data leak). |
| `jinja2` | BSD-3 | Payment page template. |
| `httpx` | BSD-3 | Outbound Graph API calls. |

**Zero-cost guarantee.** The bot only ever replies to a patient-initiated message, which
Meta bills as a free *service conversation*. Business-initiated **template messages are
paid** and are therefore forbidden in 1.0 — this is why appointment reminders are deferred
to Future Work (§9). Any change that sends an unprompted message to a patient breaks the
₹0 guarantee and must be approved by the user first.

### Development only
| Package | License | Why |
|---------|---------|-----|
| `pytest` | MIT | Test runner. |
| `pytest-asyncio` | Apache-2.0 | Async handler tests. |
| `pytest-cov` | MIT | Coverage gate (≥85% on `flow/`). |
| `ruff` | MIT | Lint + format (replaces black+flake8+isort — one tool, fewer deps). |
| `bandit` | Apache-2.0 | Security static analysis, wired into CI. |
| `pip-audit` | Apache-2.0 | CVE scan of the dependency tree, wired into CI. |

**Explicitly NOT installed:** any AI/LLM SDK, `requests` (httpx covers it), `black`,
`flake8`, `isort` (ruff covers all three), `celery`/`redis` (asyncio task suffices),
`python-dotenv` (pydantic-settings covers it), `pywa` (see below), `alembic` (see below).

**Why `pywa` was dropped (2026-07-20).** The Cloud API surface we need is four JSON
message shapes plus an HMAC-SHA256 signature check. Writing it directly against the
documented Graph API with `httpx` + stdlib `hmac` removes a wrapper whose API can drift
between versions, and which we cannot integration-test against Meta before go-live. Fewer
dependencies, full control, identical result. The adapter lives in
`whatsapp/cloud_api.py` and is under 200 lines.

**Why `alembic` was dropped (2026-07-20).** 1.0 ships a fresh schema created by
`create_all()`. Carrying a migration framework before there is anything to migrate is
unnecessary weight. Re-add it at the first schema change that must preserve live clinic
data — recorded in §9 Future work.

---

## 5. Repository layout

```
clinic-whatsapp-appointment-booking/
├── .claude/
│   ├── settings.json
│   └── skills/
│       ├── project-context/SKILL.md     # MUST run at every session start
│       ├── whatsapp-flow/SKILL.md
│       ├── git-workflow/SKILL.md
│       └── testing/SKILL.md
├── .github/workflows/ci.yml
├── config/clinic.yaml                   # the ONLY file a new clinic edits
├── docs/
│   ├── PROJECT_PLAN.md                  # this file
│   ├── PROGRESS.md                      # step-by-step build log
│   ├── SESSION_STATE.md                 # cross-session context handoff
│   ├── ARCHITECTURE.md
│   └── SETUP.md                         # clinic operator runbook
├── RECREATE_PROMPT.md                   # GITIGNORED — single-prompt rebuild
├── scripts/
│   ├── setup.ps1 / setup.sh
│   ├── seed.py
│   └── dev_tunnel.ps1
├── src/clinic_bot/
│   ├── settings.py
│   ├── main.py
│   ├── db/            models.py session.py seed.py
│   ├── whatsapp/      base.py cloud_api.py messages.py
│   ├── flow/          states.py session_store.py router.py handlers/
│   ├── scheduling/    slots.py
│   ├── payments/      upi.py qr.py
│   └── web/           routes.py templates/pay.html
├── tests/
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 6. Build sequence — feature branches

Each row is one `feature/CAB-XXXX` branch cut **from `release/1.0`**, merged back into
`release/1.0` via PR. `release/1.0 → main` only when the full suite is green.

| ID | Branch | Scope | Exit criteria |
|----|--------|-------|---------------|
| CAB-0001 | `feature/CAB-0001` | Scaffolding, venv, `pyproject.toml`, settings, `clinic.yaml`, all docs, `.claude` skills | `pytest` collects; config loads and validates |
| CAB-0002 | `feature/CAB-0002` | DB models, migrations, YAML→SQLite seeder | Seed produces doctors/services/slots; UNIQUE constraint proven by test |
| CAB-0003 | `feature/CAB-0003` | Transport abstraction + Cloud API adapter + webhook (signature verification) | Fake adapter passes contract tests; bad signature → 403 |
| CAB-0004 | `feature/CAB-0004` | FSM core, persisted session store, reset keywords, timeout | Full state-transition test matrix green |
| CAB-0005 | `feature/CAB-0005` | Welcome / Our Services / Contact Us handlers | Flow §3.1 top block verified end-to-end |
| CAB-0006 | `feature/CAB-0006` | Book New: name → service → doctor → date → slot → summary → confirm | Happy path + Change Details path green |
| CAB-0007 | `feature/CAB-0007` | Reschedule and Cancel | Slot correctly released and re-bookable |
| CAB-0008 | `feature/CAB-0008` | UPI QR, payment page with app intents, I've Paid / Need Help | QR decodes to a valid `upi://pay` URI in test |
| CAB-0009 | `feature/CAB-0009` | Full test suite, auto bug-fix pass, coverage gate, `bandit` + `pip-audit` clean | ≥85% coverage on `flow/`; zero high-severity findings |
| CAB-0010 | `feature/CAB-0010` | CI workflow, branch protection, `SECURITY.md`, CODEOWNERS | Direct push to `main` rejected |
| CAB-0011 | `feature/CAB-0011` | One-command clinic onboarding wizard (§10) | A non-technical operator gets from clone to live bot without editing code |
| CAB-0012 | `feature/CAB-0012` | Production deployment: systemd unit, Caddy, backups, deploy pipeline (§11) | Bot survives a VM reboot and a redeploy without losing bookings |

---

## 10. One-time setup — the commercial deliverable

Onboarding a clinic must be **one command**, runnable by someone who does not know Python.
This is what is actually being sold; treat it as a first-class feature, not a script.

```
python setup.py
```

`setup.py` runs an interactive wizard that:

1. Verifies Python ≥3.12, creates `.venv/`, installs pinned dependencies.
2. Prompts for clinic details — name, address, phone, working hours, break, timezone —
   and writes `config/clinic.yaml`. Re-running detects an existing file and offers to edit
   rather than overwrite.
3. Prompts for services (name, fee-from, duration) and doctors (name, specialisation,
   which services they provide, working days and hours), looping until the operator is done.
4. Prompts for UPI ID, UPI display name and advance amount; **validates the UPI ID format**
   and renders a sample QR for the operator to test-scan before continuing.
5. Prompts for Meta credentials and writes `.env` with `0600`-equivalent permissions.
6. **Live-validates the credentials** with a real Graph API call. A wrong token fails here,
   at setup, with a readable message — not silently at 2am when a patient messages.
7. Creates and seeds the SQLite database from the YAML.
8. Prints the exact **Callback URL** and **Verify Token** to paste into the Meta dashboard,
   with the click path spelled out.
9. Offers to run a self-test that drives a full fake conversation through the FSM and
   reports PASS/FAIL per step.

### Setup design rules
- **Idempotent.** Re-running never destroys existing bookings or duplicates seed data.
- **Resumable.** Answers are checkpointed, so an interrupted wizard continues where it left off.
- **No code editing, ever.** If the wizard cannot express something, that is a bug in the
  wizard, not a reason to tell the operator to edit a `.py` file.
- **Reversible.** `python setup.py --reconfigure` re-runs the wizard against existing data.
- Every prompt ships a sensible default so the operator can press Enter through the whole
  thing and get a working demo clinic.

---

## 7. Testing strategy

1. **Unit** — slot generation, UPI URI construction, YAML validation, state transitions.
2. **Flow integration** — a `FakeWhatsAppAdapter` records outbound messages; tests drive a
   whole conversation as message dicts and assert on exact button/list payloads. No network.
3. **Webhook** — signed payload fixtures against the real FastAPI app via `TestClient`.
4. **Concurrency** — two simultaneous bookings for the same slot; exactly one must win.
5. **Manual two-phone script** — `docs/SETUP.md` carries a numbered checklist for the
   Phone A / Phone B run-through.

The bug-fix loop in CAB-0009 is: run suite → any failure is diagnosed and fixed → re-run →
repeat until green. Failures are recorded in `PROGRESS.md`, never silently patched over.

---

## 8. GitHub security model

- Repo: `saisagarr1995/clinic-whatsapp-appointment-booking`, **public**.
- `main` and `release/1.0` both protected:
  - No direct pushes (including by admins — enforce-admins ON).
  - PR required, ≥1 approval, stale approvals dismissed on new commits.
  - Required status check: `ci`.
  - Force-push and branch deletion blocked.
  - Conversation resolution required.
- Merge path is strictly `feature/CAB-XXXX → release/1.0 → main`.
- `CODEOWNERS` assigns everything to `@saisagarr1995`.
- Outside collaborators: none. Issues/PRs from forks run CI without secrets.
- **No secrets in the repo.** `.env`, `*.db`, `RECREATE_PROMPT.md` are gitignored.
  `bandit` + `pip-audit` + secret-scanning + Dependabot alerts enabled.

---

## 9. Future work (not 1.0)
- Admin dashboard (FastAPI + HTMX) — candidate `release/1.1`.
- Automated UPI reconciliation via bank/UPI webhook.
- Appointment reminders (24h / 2h before) via template messages.
- Multi-language (Telugu/Hindi) message catalogue — the message layer is already
  centralised in `whatsapp/messages.py` to make this a data-only change.

---

## Change log
| Date | Change |
|------|--------|
| 2026-07-20 | Initial plan created and locked. |
