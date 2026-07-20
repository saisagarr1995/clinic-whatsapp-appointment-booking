# Security Policy

This system handles patient names, phone numbers and appointment details — health-adjacent
personal data. Security issues are treated seriously.

## Reporting a vulnerability

**Do not open a public issue.**

Use GitHub's private reporting: **Security → Report a vulnerability** on this repository.

Please include what the issue is, how to reproduce it, and what an attacker could achieve.
Expect an acknowledgement within 72 hours.

## Security model

### The webhook is the only endpoint an attacker can reach with intent

- Every `POST /webhook` must carry a valid `X-Hub-Signature-256` — an HMAC-SHA256 of the
  **raw request body** using the Meta app secret, compared in constant time. Without it,
  anyone who learned the URL could inject fake patient messages and create bookings.
- The check **fails closed**: an unset app secret rejects everything rather than allowing
  everything.
- The `GET /webhook` handshake requires the configured verify token.
- Every Meta message id is recorded **before** the 200 is returned, so a retried delivery
  cannot replay a patient's action into a duplicate booking.

### Clinic isolation

Each clinic runs as its own process with its own database file, under systemd with
`ReadWritePaths` scoped to that clinic's directory alone. A compromised clinic process
cannot read or modify another clinic's data. This is deliberate: shared-database
multi-tenancy was rejected because one missing `WHERE clinic_id = ...` would leak patient
data between clinics.

### Patient data access

- A patient may only act on bookings belonging to their own WhatsApp id — enforced on
  every reschedule and cancel.
- Payment pages are reachable only with the booking reference, are marked `noindex`, and
  return 410 once the booking is no longer payable.
- Booking references are validated against a strict pattern before ever being used in a
  filesystem path.

### Secrets

- Credentials live only in `.env`, which is gitignored and `chmod 600`.
- `.env`, `*.db` and `RECREATE_PROMPT.md` are never committed.
- Each clinic has its own Meta credentials; a leak is contained to one clinic.

### Hardening

- The app binds `127.0.0.1`; Caddy terminates TLS and proxies inward. It is never exposed
  directly.
- `/docs`, `/redoc` and `/openapi.json` are disabled — a public repo plus public API docs
  would hand an attacker the full surface.
- systemd sandboxing: `ProtectSystem=strict`, `PrivateTmp`, `NoNewPrivileges`,
  `MemoryDenyWriteExecute`, a `SystemCallFilter` allowlist, and a per-clinic `MemoryMax`
  so one clinic cannot starve the others.
- Automatic security updates via `unattended-upgrades`.
- CI runs `bandit` and `pip-audit` on every push; findings are fixed, not suppressed.

## What this system deliberately does NOT do

- **It does not verify payments.** "I've Paid" is a patient declaration. Bookings move to
  `AWAITING_VERIFICATION` and clinic staff confirm the money arrived. Do not treat that
  status as proof of payment.
- **It does not store card or bank details.** Payment happens entirely inside the
  patient's own UPI app; we only generate a request.
- **It does not send unprompted messages.** The bot only ever replies.

## Known accepted limitation

There is a narrow race for **overlapping but non-identical** appointment start times
confirmed in the same instant for the same doctor. Identical starts are impossible — a
partial unique database index prevents them. Closing the overlapping case fully requires
row locking that SQLite does not provide. It requires two patients to confirm overlapping
times for the same doctor at the same moment; both bookings appear in the clinic's day
list, so it is visible rather than silent. Documented in
`src/clinic_bot/scheduling/slots.py`.

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅ |
