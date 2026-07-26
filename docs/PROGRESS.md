# Build Progress Log

Step-by-step record of what was built and why. Newest entries at the bottom.
**Updated whenever anything is built or the plan changes** — see `CLAUDE.md`.

---

## 2026-07-20 — Session 1

### Requirements and decisions

Captured the full booking flow from the user's specification. Four architectural
questions were resolved before any code was written:

1. **WhatsApp transport.** The user asked for "open source" and "safe and secure". These
   pull in opposite directions, because WhatsApp is a proprietary network. Reverse-
   engineered libraries (`neonize`, Baileys) are open source but violate WhatsApp's ToS,
   get numbers banned, and have unreliable interactive-button rendering — fatal for a
   button-driven flow being sold to clinics. **Decided: Meta's official Cloud API**, with
   100% open-source code on our side. Recorded as PROJECT_PLAN §2 D1.
2. **UPI payment.** WhatsApp will not open a `upi://` link from chat text.
   **Decided:** QR image + copyable UPI ID + a self-hosted payment page carrying
   app-specific intent buttons.
3. **Webhook exposure.** cloudflared for local testing (later superseded by real hosting).
4. **Clinic onboarding.** `config/clinic.yaml` + SQLite seed, so onboarding is a data
   change and never a code change.

### Scaffolding (CAB-0001)

Folder structure, Python 3.12 venv, `pyproject.toml`, `.gitignore`, `.env.example`.
Dependency list kept deliberately small and each package justified in PROJECT_PLAN §4.

**Dropped two planned dependencies:**
- `pywa` — the Cloud API surface we need is four JSON shapes plus an HMAC check. Writing
  it directly against the documented Graph API removes a wrapper that could drift and that
  we cannot integration-test before go-live. The adapter is under 200 lines.
- `alembic` — 1.0 creates a fresh schema. Carrying a migration framework before there is
  anything to migrate is dead weight. Re-add at the first schema change that must preserve
  live clinic data.

### Configuration and data layer (CAB-0002)

`clinic_config.py` validates `clinic.yaml` strictly and fails loudly at startup. Validation
deliberately covers mistakes a *clinic operator* would make, not just type errors:
service names exceeding WhatsApp's 24-character row limit, a doctor referencing an
undefined service, a service no doctor provides (unbookable — a dead end for the patient),
a UPI ID that is really a phone number, a phone number without a country code.

Models use a **partial unique index** on `(doctor_id, starts_at)` limited to
slot-occupying statuses. This is the anti-double-booking guarantee, enforced by SQLite
itself rather than by application logic, so two concurrent webhook deliveries cannot both
win. Being partial, a cancelled booking correctly frees its slot.

Seeder is idempotent — verified by running it twice and confirming counts stayed at
8 services / 4 doctors / 17 schedules. Removed entities are deactivated, never deleted,
so historical bookings keep their foreign keys.

### Transport layer (CAB-0003)

`whatsapp/base.py` defines transport-agnostic message types that **validate WhatsApp's
limits on construction** — 3 buttons, 10 list rows, 1024-char body, 24-char row titles.
Structural violations raise; display text is clipped. The point is that a limit breach
fails in our test suite rather than silently in a patient's chat.

`cloud_api.py` handles Graph API JSON, HMAC-SHA256 signature verification (constant-time),
and webhook parsing that ignores the delivery-status callbacks Meta sends constantly.

`fake.py` records outbound messages so the entire flow is testable with no network.

### Availability engine (CAB-0004/0006)

Slots sit on a `slot_minutes` grid but appointments occupy the **service's** duration, so
a 60-minute root canal on a 30-minute grid correctly blocks two slots. Computed by
interval overlap, not exact-start comparison.

A residual race remains for *overlapping but non-identical* starts confirmed in the same
instant. Closing it fully needs row locking SQLite does not offer. It is documented in the
module docstring rather than hidden — it requires two patients to confirm the same doctor
at overlapping times in the same moment, and the clinic sees both in the day list.

### Conversation flow (CAB-0005 through CAB-0008)

Router implements PROJECT_PLAN §3.1 verbatim, including the exact wordings the user
specified. Design rules enforced throughout: the bot never dead-ends (every state has a
fallback that nudges *and* re-asks), availability is re-checked at Confirm, and a patient
can only act on their own bookings.

Payment sends QR image → UPI details → action buttons, in that order, so the instruction
text reads as a caption for a QR the patient can already see.

---

## Bugs found and fixed

### BUG-001 — Session timestamps used server wall-clock time (critical, production)

**Symptom.** Every booking test failed at the third message with "Your session timed out".

**Root cause.** `ConversationSession.updated_at` was declared with
`onupdate=dt.datetime.now`. `session_store.save()` assigns that column explicitly, but
when the value it wrote was *unchanged*, SQLAlchemy's change detection omitted the column
from the UPDATE statement — at which point `onupdate` fired and substituted
`datetime.now()`, i.e. **server wall-clock time**, into a column that the rest of the app
compares against **clinic-timezone time** from `clock.now()`.

**Why this mattered far beyond the tests.** On a server in UTC serving a clinic in IST
(+5:30), every stored session timestamp would land 5.5 hours in the past. The expiry check
would therefore treat *every* session as stale, and every patient would be bounced back to
the welcome menu on their second tap. The bot would have been unusable in production, and
the cause would have been very hard to find from the symptom.

**Fix.** All datetime column defaults routed through `clock.now()` via a `_now()` helper.
`onupdate` removed from `ConversationSession.updated_at` entirely, with a comment
explaining why it must not come back. Regression test in
`tests/test_session.py::test_session_timestamps_use_the_clinic_clock_not_server_wall_time`,
plus `test_a_long_conversation_never_self_expires`.

### BUG-002 — Services overview could exceed WhatsApp's body limit (found by inspection)

**Symptom.** Not yet observed; caught while writing tests. The sample clinic's 8 services
produce ~840 characters against a 1024 limit. A clinic with 12+ services would exceed it
and `_clip()` would silently truncate the message mid-sentence.

**Fix.** `views.chunk_body()` splits long copy across multiple messages on blank-line
boundaries, keeping each service block intact. Test
`test_services_overview_never_exceeds_whatsapp_body_limit` asserts no message exceeds the
limit and that no ellipsis appears.

### BUG-003 — Two reschedule tests were wrong, not the product

**Symptom.** `test_reschedule_moves_the_booking_and_keeps_the_reference` and
`test_rescheduling_frees_the_original_slot` failed.

**Root cause.** The tests picked slot index 0, which is the patient's *own* current slot —
correctly offered back by `available_slots(exclude_booking_id=...)` so a patient who opens
Reschedule and changes their mind can keep their existing time. The "reschedule" was a
no-op move to the same slot.

**Fix.** Tests pick index 1. Added
`test_reschedule_offers_the_patients_own_slot_back` to lock in the behaviour that caused
the confusion, so it is now covered rather than incidental.

### BUG-004 — Default bind address was `0.0.0.0` (security, low)

Found by `bandit` (B104). The default meant that anyone running the app directly, outside
systemd, would expose it on all interfaces without Caddy in front. Changed the default to
`127.0.0.1`; production binds localhost explicitly and Caddy proxies inward. Suppressing
the warning was rejected — the finding was correct.

### BUG-005 — `pytest` 8.4.2 carried a known CVE

Found by `pip-audit`: PYSEC-2026-1845. Pinned to `>=9.0.3`. Dev-only dependency, but the
CI gate should stay clean so a real one is never lost in the noise.

---

## Infrastructure decisions (added mid-session, at the user's direction)

The user clarified two things that changed the deployment design materially:

**1. Nothing may run on their laptop; they cannot pay for hosting.**

Clarified a misconception first: SQLite is not a server to install — it is a file, and the
engine ships with Python. But the real point stood: a bot on a laptop dies when the lid
closes.

Surveyed free hosting honestly. Free tiers that sleep (Render) or expire (Railway,
30-day Postgres) were rejected: a bot taking ~50 seconds to answer the first "Hi" is not
sellable. **Decided: Oracle Cloud Always Free** — 4 ARM cores, 24 GB RAM, free forever,
never sleeps. Requires a card for identity verification only. The user confirmed they can
complete this.

Stated plainly that no free, always-on, production hosting exists with *no* payment method
at all, rather than offering a sleeping free tier and letting a clinic discover it.

**2. Scale target is 50 clinics × 50 patients/day.**

This invalidated the original "one deployment = one clinic" assumption. Ran the numbers:
2,500 bookings/day, ~35,000 messages/day, ~1 msg/sec average and ~5 msg/sec peak,
~275 MB/year of data. Comfortably within one Always Free VM. All messages remain replies
to patient-initiated conversations, so **WhatsApp cost stays ₹0 at full scale**.

Chose **process + database per clinic** over shared-database multi-tenancy. The deciding
factor was not performance but data safety: in a shared design a single missing
`WHERE clinic_id = ...` leaks one clinic's patient medical data to another. Per-clinic
processes push isolation down to the operating system, where it cannot be undone by a
future code change. It also left the already-written, already-tested code unchanged.

Built: `clinic-bot@.service` systemd template with per-clinic sandboxing
(`ReadWritePaths` scoped to that clinic's folder, `MemoryMax`, full hardening set), a
`clinic-bot.target` for fleet-wide control, path-based Caddy routing so one certificate
covers all clinics, and `fleet.sh` (`clinic-fleet`) providing add / remove / list /
start / stop / restart / logs / health / backup / restore / deploy. Deploy restarts
clinics one at a time with a health check between each, so a bad release cannot take down
all 50.

Backups: nightly `sqlite3 .backup` per clinic — a consistent snapshot even while the bot
is writing, which `cp` does not guarantee — verified with `PRAGMA integrity_check` and
discarded if the check fails. 30-day retention, as the user requested. `restore` preserves
the pre-restore database before overwriting.

---

## Verification status at end of session 1

```
pytest      152 passed
ruff        All checks passed
bandit      0 high, 0 medium
pip-audit   No known vulnerabilities found
```

**Not yet verified:** anything requiring real WhatsApp — message delivery, button
rendering on a handset, QR scanning, UPI apps opening. That is what
`docs/TWO_PHONE_TEST.md` exists for, and it has not been run yet.

---

# Session 2 — 2026-07-26 — CAB-0014: laptop hosting and the clinic fleet

## What changed and why

The user changed the hosting decision: the product now runs on their Windows
laptop, not (yet) on an Oracle VM, and must serve **many clinics, each with its own
database, driven by one registry file**. They also asked for the QR to go and for
memory use to stay low. Four locked decisions were amended — all recorded in
`PROJECT_PLAN.md` at the decision they change.

## The fleet registry

`config/clinics.yaml` is now the only file edited to onboard a clinic. Each entry
yields, automatically, its own config, database (`data/clinics/<slug>.db`), Meta
credentials (`config/secrets/<slug>.env`, gitignored) and URL scope (`/c/<slug>/`).

The refactor was to three global singletons that hard-wired one clinic:
`get_clinic_config()` and `get_settings()` were `@lru_cache`'d, and `db/session.py`
held a module-global `_engine`. Engines are now cached per database URL, and
`registry.Clinic` carries config, session factory, credentials and base URL.

## One process, not one per clinic (D13 amended)

D13 originally called for a process per clinic, giving OS-level isolation. On a
laptop that costs ~85 MB each. The fleet now runs in one process that resolves the
clinic from the URL.

**Measured, not estimated:** 85.2 MB for one clinic; 86.8 MB for five — about
0.4 MB per additional clinic, against ~425 MB for five processes. After dropping
Pillow the single-clinic figure fell to 82.1 MB.

What was given up is OS-level isolation, so the isolation is now proven by test
instead of assumed. `tests/test_multi_clinic.py` asserts that a booking in one
clinic is invisible to another, that a payment reference does not resolve at
another clinic, and — the important one — that **a webhook signature valid for one
clinic is rejected by every other**, because the Meta app secret is per clinic.
If those tests are ever weakened, D13 must be revisited.

## QR removed (D4 amended)

`qrcode[pil]` pulled in Pillow, the heaviest dependency in the tree, to render one
small PNG. The patient pays from the handset holding the chat, where the payment
page's app-chooser buttons and the copyable VPA already complete the journey. The
QR only helped someone scanning from a second device — that is the accepted cost.
Removed `payments/qr.py`, the `/qr/{ref}.png` route, the `ImageMessage` from the
payment reply, and the QR block from `pay.html`.

## Offline simulator

`/c/<slug>/sim` drives the real state machine against the real database through the
existing `FakeAdapter`, so the whole flow is validated with no Meta account, no
credentials and no tunnel. Buttons and list rows post back the true wire ids.

It bypasses signature verification by design, so it is gated on `SIMULATOR=true`,
defaulting to **false**, and the router is not registered at all when off.
`tests/test_simulator.py` asserts the endpoints 404 by default.

## Verification

```
pytest      180 passed   (was 152; +28 for fleet isolation and the simulator)
ruff        All checks passed
bandit      0 high, 0 medium
pip-audit   No known vulnerabilities found
memory      82.1 MB one clinic · 86.8 MB five clinics (measured RSS)
```

Validated live over HTTP, not only in tests: a full booking was driven through the
simulator end to end (`SDC-ALE7Y`), and the payment page rendered with a working
`upi://` link and no image tag.

## Known inconsistency left behind

`deploy/fleet.sh` and `deploy/clinic-bot@.service` still describe the old
process-per-clinic model and were **not** reworked. `deploy/Caddyfile` was updated
to pass `/c/<slug>/` through unchanged. The VM path must be reconciled before
`DEPLOYMENT.md` is followed again — noted in `SESSION_STATE.md`.

---

# Session 3 — 2026-07-26 — CAB-0015: payment verification, and two latent bugs

The user asked how the clinic would know a patient had really paid, and for a
correctness pass plus dead-code removal. Both questions had real answers.

## BUG-006 — `CONFIRMED` was unreachable; a false claim held a slot forever

`booking_service` documented `AWAITING_VERIFICATION --(staff)--> CONFIRMED`, but
**no code path anywhere set `CONFIRMED`**, and there was no staff-facing interface
of any kind. Combined with `declare_paid()` clearing `hold_expires_at`, and
`expire_stale_holds()` only sweeping `PENDING_PAYMENT`, the consequences were:

* Any patient could tap "I've Paid" without paying and occupy that slot permanently.
* Nobody at the clinic could see, confirm or reject the claim.
* `CONFIRMED` was dead enum weight.

**Cause.** The plan (§1 non-goals) said "clinic staff verify" and the admin dashboard
was deferred out of 1.0 — so the verification step was specified but never built, and
nothing failed loudly because the happy path looked complete to the patient.

**Fix.** Three parts, none of which pretend the software can see money move:

1. After "I've Paid" the patient is asked for their **UPI reference (UTR)** — a new
   `ASK_UTR` state with a `Skip` button. Stored on the booking as patient-supplied
   text, explicitly not treated as proof.
2. `confirm_booking()` / `reject_payment()` — the only writers of `CONFIRMED`. Both
   refuse to act on a booking that is not `AWAITING_VERIFICATION`, so a cancelled or
   unpaid booking cannot be confirmed by a typo. `reject` frees the slot at once.
3. `clinic_admin.py payments|confirm|reject` — the staff queue, oldest wait first.

Deliberately **not** done: auto-expiring unverified claims. A patient who genuinely
paid must not lose their appointment to a timer. The cost — a false claim blocks a
slot until reviewed — is stated in `PROJECT_PLAN.md` §3.1.1 and surfaced by the
`WAITING` column.

Also deliberately not done: messaging the patient on confirmation. That needs a paid
WhatsApp template message and would break the ₹0 guarantee.

Copy changed so the bot no longer says "Your appointment is booked" on a mere claim;
it now says the payment is *being verified*. A test asserts the bot never claims
"payment received" / "appointment is confirmed".

## BUG-007 — the clinic timezone was silently ignored on Windows

`clock._clinic_zone()` caught `(ZoneInfoNotFoundError, Exception)` — a blanket catch
that swallowed everything and returned `None`, falling back to machine-local time.

Windows ships no IANA time zone database, so `ZoneInfo("Asia/Kolkata")` **always
raised on this laptop**. Every slot, min-notice window and hold expiry was being
computed in the laptop's local time, not the clinic's.

It was invisible because the laptop is already on IST, so local time and Asia/Kolkata
agreed to the minute — and the test suite freezes the clock, so `_clinic_zone()` was
never exercised. It surfaced only when the blanket `except` was narrowed during this
pass and the app started returning 500s.

**Fix.** Added `tzdata` (Apache-2.0, justified in PLAN §4); `ClinicInfo.timezone` now
validates that the zone resolves at config load, so a bad or unavailable timezone
fails at `clinic_admin.py check` rather than mid-conversation; `clock` logs loudly
instead of silently falling back. Regression test included.

## Fleet timezone guard

`clock` is process-wide but the fleet is not, so two clinics in different timezones
would have had one of them silently computed in the other's local time.
`registry.validate_all()` now refuses to start such a fleet with an explicit message.
Making `clock` per-clinic is the expensive fix, and is only worth it if this is hit.

## Removed

* `ImageMessage` and its Cloud API payload branch, `FakeAdapter.images()` and the
  simulator's image rendering — dead since the QR was dropped in CAB-0014.
* `Settings.graph_url`, `Settings.messages_url`, `Settings.missing_credentials()`,
  `whatsapp_business_account_id` — superseded by per-clinic `ClinicCredentials`.
  `CloudApiAdapter` now *requires* credentials; there is no process-wide Meta identity.
* `deploy/fleet.sh`, `deploy/clinic-bot@.service`, `deploy/clinic-bot.target`,
  `deploy/install_server.sh`, `docs/DEPLOYMENT.md` — all built on the
  process-per-clinic model that D13 replaced. They would have started one process per
  clinic against databases the single fleet process owns. Recoverable from git history
  (commit `ffdf1fe`) if the VM path is rebuilt.
* The CI `shellcheck` job, which had no shell scripts left to check. CI now validates
  the whole fleet registry via `clinic_admin.py check` instead of one hardcoded file.

## Verification

```
pytest      202 passed   (was 180)
ruff        All checks passed
bandit      No issues identified
pip-audit   No known vulnerabilities found
```

Driven live end to end, not only in tests: booking → "I've Paid" → a rejected junk
UTR → a valid UTR → staff queue → confirm → queue empty → double-confirm correctly
refused.

**Schema note.** `bookings` gained `payment_ref`, `verified_at`, `verified_by`.
`create_all()` does not alter existing tables and there is no migration framework
(PLAN §4), so existing databases must be recreated. Only throwaway local data existed.
