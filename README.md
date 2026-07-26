# Clinic WhatsApp Appointment Booking

A WhatsApp appointment booking bot for dental clinics. A patient messages the clinic,
taps through service → doctor → date → time, confirms, and pays a UPI advance — with no
staff involvement and **no AI**.

[![CI](https://github.com/saisagarr1995/clinic-whatsapp-appointment-booking/actions/workflows/ci.yml/badge.svg)](https://github.com/saisagarr1995/clinic-whatsapp-appointment-booking/actions/workflows/ci.yml)

---

## Why this exists

Clinics lose bookings to missed calls. This answers every patient instantly, 24/7, in the
app they already use.

| | |
|---|---|
| **AI cost** | ₹0 — deterministic state machine, no LLM anywhere |
| **WhatsApp cost** | ₹0 — the bot only ever *replies*, which Meta bills as free service conversations |
| **Infrastructure cost** | ₹0 — runs on a laptop via Tailscale Funnel, or an Oracle Cloud Always Free VM |
| **Onboarding a clinic** | Add a line to `config/clinics.yaml`. No code changes, ever. |
| **Capacity** | 50 clinics × 50 patients/day. Measured: 82 MB for one clinic, 87 MB for five |

Every dependency is MIT, Apache-2.0 or BSD. The bot runs on Meta's **official** WhatsApp
Cloud API — it does not use reverse-engineered libraries, which violate WhatsApp's terms
and get clinic numbers banned.

---

## What a patient sees

```
Patient: Hi

Bot:     Hello! 👋
         Welcome to Smile Dental Clinic
         How can we help you today?
         [Book Appointment] [Our Services] [Contact Us]

Patient: (taps Book Appointment → Book New)

Bot:     Great! Let's get you booked in. 😊
         May I have your full name please?

Patient: Rajesh Kumar

Bot:     Thank you, Rajesh Kumar!
         Which service do you need today?  [View Services]

         → picks service → doctor → date → time slot

Bot:     📋 Booking Summary
         👤 Rajesh Kumar · 🦷 Root Canal · 👨‍⚕️ Dr. Priya Sharma
         📅 Tomorrow (Tue, 4 Aug) · 🕐 11:00 AM
         💳 Advance to confirm: ₹200
         [Confirm] [Change Details]

Bot:     ✅ Appointment reserved! Reference: SDC-K3M7Q
         UPI ID: smiledental@okhdfcbank
         👉 Tap to pay: https://.../c/smile/pay/SDC-K3M7Q
         [I've Paid] [Need Help]

Patient: (taps I've Paid)

Bot:     Type the UPI reference number from your payment app  [Skip]

Patient: 438291750163

Bot:     🙏 Thank you, Rajesh! Your slot is reserved and your
         payment is being verified.
```

---

## Features

- **Book, reschedule and cancel** entirely in WhatsApp
- **Real availability** — respects each doctor's working days and hours, lunch breaks,
  closing time, and a minimum-notice window
- **No double booking**, guaranteed by a database constraint rather than by application
  logic, so concurrent requests cannot both win
- **Multi-slot appointments** — a 60-minute treatment correctly blocks two 30-minute slots
- **UPI payment** — copyable UPI ID and a payment page with GPay / PhonePe / Paytm /
  CRED / BHIM buttons
- **Payment verification by a human** — the patient supplies their UPI reference, and
  clinic staff confirm or reject it against the bank statement. The bot never claims a
  payment was received, because it genuinely cannot know
- **Slot holds** expire after 15 minutes so abandoned bookings free themselves
- **Never dead-ends** — any unrecognised input re-prompts rather than going silent
- **Survives restarts** mid-conversation; sessions live in the database
- **Fleet management** — many clinics from one process, each with its own database and
  its own Meta credentials; isolation proven by test
- **Offline simulator** — validate the entire conversation with no Meta account

---

## Quick start (local, for development)

```bash
git clone https://github.com/saisagarr1995/clinic-whatsapp-appointment-booking.git
cd clinic-whatsapp-appointment-booking

python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # Linux/macOS

pip install -e ".[dev]"
cp .env.example .env              # Meta credentials are optional to start

python scripts/clinic_admin.py seed smile
pytest -q                         # 202 tests, no network needed
.\scriptsun_local.ps1           # then open /c/smile/sim
```

You do **not** need WhatsApp credentials to run the test suite — the whole conversation
flow is testable offline.

---

## Running it

See **[docs/LOCAL_HOSTING.md](docs/LOCAL_HOSTING.md)** — start the fleet, add clinics,
expose a public HTTPS webhook with Tailscale Funnel, and verify payments.

```powershell
.\scriptsun_local.ps1                                   # start the fleet
python scripts\clinic_admin.py add ortho-care             # onboard a clinic
python scripts\clinic_admin.py seed ortho-care
python scripts\clinic_admin.py payments ortho-care        # who is awaiting verification
python scripts\clinic_admin.py confirm ortho-care SDC-K3M7Q
```

One process serves every clinic at `/c/<slug>/`, each with its own SQLite database and
its own Meta app secret — so a webhook signature valid for one clinic is rejected by
every other.

---

## Configuring a clinic

Everything clinic-specific lives in one file — [`config/clinic.yaml`](config/clinic.yaml):

```yaml
clinic:
  name: "Smile Dental Clinic"
  phone: "+919000000000"
  hours:
    open: "09:00"
    close: "20:00"
    days: [mon, tue, wed, thu, fri, sat]
    break: { start: "13:30", end: "14:30" }

payment:
  upi_id: "smiledental@okhdfcbank"
  advance_amount: 200

services:
  - code: root_canal
    name: "Root Canal (RCT)"
    fee_from: 5000
    duration_minutes: 60

doctors:
  - code: dr_priya
    name: "Dr. Priya Sharma"
    specialization: "Endodontist"
    services: [consultation, root_canal]
    working_days: [mon, wed, fri, sat]
```

The config is validated strictly at startup — a service no doctor provides, a name too
long for a WhatsApp list row, or a malformed UPI ID all fail immediately with a clear
message, rather than breaking a patient's booking later.

---

## Documentation

| Document | What it covers |
|---|---|
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | The locked plan, every decision and why |
| [docs/LOCAL_HOSTING.md](docs/LOCAL_HOSTING.md) | Running the fleet, going live, verifying payments |
| [docs/TWO_PHONE_TEST.md](docs/TWO_PHONE_TEST.md) | Manual test script for two handsets |
| [docs/PROGRESS.md](docs/PROGRESS.md) | Build log, including every bug's root cause |
| [docs/SESSION_STATE.md](docs/SESSION_STATE.md) | Current status and next steps |
| [SECURITY.md](SECURITY.md) | Security model and how to report a vulnerability |

---

## Tech stack

Python 3.12 · FastAPI · SQLAlchemy · SQLite · Jinja2 · httpx
Meta WhatsApp Cloud API · Tailscale Funnel · Caddy

No AI libraries. No paid services. Nothing that phones home.

---

## Contributing

`main` is protected and represents what is live at customer clinics. Work goes
`feature/CAB-XXXX → release/1.0 → main`. See
[.claude/skills/git-workflow/SKILL.md](.claude/skills/git-workflow/SKILL.md).

---

## License

MIT — see [LICENSE](LICENSE).
