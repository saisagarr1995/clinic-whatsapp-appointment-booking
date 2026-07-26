# Two-Phone Manual Test Script

Print this. Work through it in order. Tick every box.

- **Phone A** = the clinic's WhatsApp number (the Cloud API number)
- **Phone B** = the patient (your second handset, whitelisted in the Meta dashboard)

> The automated suite (`pytest`, 202 tests) already proves the conversation logic.
> This script exists to prove the things software cannot check by itself: that Meta
> delivers the messages, that buttons render as buttons, and that a UPI app actually
> opens with the right details.

---

## Before you start

| # | Check | ✓ |
|---|-------|---|
| 0.1 | `python scripts/clinic_admin.py list` shows the clinic | ☐ |
| 0.2 | `curl https://<domain>/health` returns `"status":"ok"` | ☐ |
| 0.3 | Meta dashboard → webhook shows **Verified**, `messages` field subscribed | ☐ |
| 0.4 | Phone B's number is in the Meta test-recipient list (max 5) | ☐ |
| 0.5 | Phone B has at least one UPI app installed (GPay / PhonePe / Paytm) | ☐ |
| 0.6 | Watch the server console while testing (or `logsleet.log`) | ☐ |
| 0.7 | **`SIMULATOR=false` in `.env`** — the app is publicly reachable now | ☐ |

If 0.3 fails, nothing else will work. Fix it first.

---

## Test 1 — Welcome

| # | From Phone B | Expected on Phone B | ✓ |
|---|--------------|---------------------|---|
| 1.1 | Send `Hi` | Reply arrives in **under 5 seconds** | ☐ |
| 1.2 | | Greeting names the clinic correctly | ☐ |
| 1.3 | | Exactly **three tappable buttons**: Book Appointment, Our Services, Contact Us | ☐ |
| 1.4 | | Buttons render as buttons, **not** as plain text like "1. Book" | ☐ |

**If 1.4 fails** the number is not a proper Cloud API business number. Stop and check setup.

Repeat 1.1 with `hello`, `Menu`, `start` — each must return the same welcome. ☐

---

## Test 2 — Our Services

| # | From Phone B | Expected | ✓ |
|---|--------------|----------|---|
| 2.1 | Tap **Our Services** | Every service from `clinic.yaml` is listed | ☐ |
| 2.2 | | Each shows "Consultation fee starts at ₹…" | ☐ |
| 2.3 | | Fees match `clinic.yaml` exactly | ☐ |
| 2.4 | | Clinic timings shown (open, close, lunch break, closed days) | ☐ |
| 2.5 | | **No text is cut off mid-sentence** or ends in `…` | ☐ |
| 2.6 | | A follow-up message offers a **Book Appointment** button | ☐ |
| 2.7 | Tap **Book Appointment** | Booking menu opens | ☐ |

---

## Test 3 — Contact Us

| # | From Phone B | Expected | ✓ |
|---|--------------|----------|---|
| 3.1 | Send `Hi`, tap **Contact Us** | Clinic phone number shown, correct | ☐ |
| 3.2 | | Address shown, correct | ☐ |
| 3.3 | | Timings shown | ☐ |
| 3.4 | | Book Appointment button present and works | ☐ |

---

## Test 4 — Book New, the happy path

| # | From Phone B | Expected | ✓ |
|---|--------------|----------|---|
| 4.1 | `Hi` → **Book Appointment** | Three buttons: Book New, Reschedule, Cancel | ☐ |
| 4.2 | Tap **Book New** | Message 1: "Great! Let's get you booked in" | ☐ |
| 4.3 | | Message 2: "May I have your full name please?" | ☐ |
| 4.4 | Type `Rajesh Kumar` | "Thank you, **Rajesh Kumar**!" | ☐ |
| 4.5 | | Second message: "Which service do you need today?" + **View Services** button | ☐ |
| 4.6 | Tap **View Services** | A scrollable **list** opens (not buttons) | ☐ |
| 4.7 | | Each row shows the service name and starting fee | ☐ |
| 4.8 | Choose **Root Canal (RCT)** | Doctor list appears | ☐ |
| 4.9 | | **Only doctors who do root canals** are shown (Dr. Priya in the sample config) | ☐ |
| 4.10 | Choose a doctor | Date list appears | ☐ |
| 4.11 | | Dates show as Today / Tomorrow / Day, DD Mon | ☐ |
| 4.12 | | **Only that doctor's working days** appear | ☐ |
| 4.13 | Choose a date | Time slot list appears | ☐ |
| 4.14 | | No slot is in the past; none within the next hour | ☐ |
| 4.15 | | No slot falls inside the lunch break | ☐ |
| 4.16 | Choose a slot | Full booking summary appears | ☐ |
| 4.17 | | Summary shows name, service, doctor, date, time, fee, advance | ☐ |
| 4.18 | | Two buttons: **Confirm** and **Change Details** | ☐ |

---

## Test 5 — Change Details

| # | From Phone B | Expected | ✓ |
|---|--------------|----------|---|
| 5.1 | Tap **Change Details** | Returns to "Which service do you need today?" | ☐ |
| 5.2 | | **Does not ask for your name again** | ☐ |
| 5.3 | Pick a different service and reach the summary | Summary reflects the **new** choices | ☐ |

---

## Test 6 — Payment

| # | From Phone B | Expected | ✓ |
|---|--------------|----------|---|
| 6.1 | Tap **Confirm** | Payment message arrives (**no image** — the QR was removed) | ☐ |
| 6.2 | | Booking reference shown (e.g. `SDC-K3M7Q`) | ☐ |
| 6.3 | | UPI ID and UPI name shown, matching `clinic.yaml` | ☐ |
| 6.4 | | Advance amount correct | ☐ |
| 6.5 | | A payment link is present | ☐ |
| 6.6 | | Separate message with buttons **I've Paid** and **Need Help** | ☐ |
| 6.8 | Tap the payment link | Payment page opens in the browser | ☐ |
| 6.9 | | Page shows amount, UPI ID, a **Copy** button and the app buttons | ☐ |
| 6.10 | Tap **Copy** | UPI ID copied to clipboard | ☐ |
| 6.11 | Tap **Pay with any UPI app** | Android UPI app chooser opens | ☐ |
| 6.12 | Tap **Google Pay** | GPay opens with details pre-filled | ☐ |
| 6.13 | Tap **PhonePe** | PhonePe opens (or says not installed — acceptable) | ☐ |

> **Do not complete a real payment** unless you intend to. Verifying that the app
> opens with the right VPA and amount is sufficient.

---

## Test 7 — After payment

| # | From Phone B | Expected | ✓ |
|---|--------------|----------|---|
| 7.1 | Tap **Need Help** | Clinic's phone number shown | ☐ |
| 7.2 | | An **I've Paid** button is still available | ☐ |
| 7.3 | Tap **I've Paid** | Asked for the **UPI reference number**, with a **Skip** button | ☐ |
| 7.4 | Type `hello` | Politely refused, re-prompted — must not dead-end | ☐ |
| 7.5 | Type a 12-digit reference | Thank-you naming the patient, echoing the reference | ☐ |
| 7.6 | | Says the payment is **being verified** — NOT that it is confirmed | ☐ |
| 7.7 | | Shows reference, doctor, date, time, address | ☐ |

### Then, on the laptop — the staff half of the flow

| # | Action | Expected | ✓ |
|---|--------|----------|---|
| 7.8 | `python scripts/clinic_admin.py payments <slug>` | The booking is listed, with the UPI reference the patient typed | ☐ |
| 7.9 | Check that reference against the clinic's UPI/bank statement | It matches (or does not) | ☐ |
| 7.10 | `... confirm <slug> <REF>` | Booking becomes `CONFIRMED` | ☐ |
| 7.11 | `... payments <slug>` again | Queue is now empty | ☐ |
| 7.12 | `... confirm <slug> <REF>` again | Refused — already confirmed | ☐ |

> The patient is **not** messaged when you confirm. Telling them would need a paid
> WhatsApp template message. Phone them if they need to hear it.

---

## Test 8 — Double booking (needs a second patient number, or reuse Phone B after a reset)

| # | Action | Expected | ✓ |
|---|--------|----------|---|
| 8.1 | Book slot 10:00 with Dr. Priya from Phone B | Booking confirmed | ☐ |
| 8.2 | Start a new booking, same doctor, same date | **10:00 is no longer offered** | ☐ |
| 8.3 | Book a 60-minute service (Root Canal) at 11:00 | Confirmed | ☐ |
| 8.4 | Start again, same doctor, same date | **Both 11:00 and 11:30 are gone** | ☐ |

Step 8.4 is the one people get wrong. A 60-minute treatment must consume two 30-minute slots.

---

## Test 9 — Reschedule

| # | From Phone B | Expected | ✓ |
|---|--------------|----------|---|
| 9.1 | `Hi` → Book Appointment → **Reschedule** | Your existing appointments are listed | ☐ |
| 9.2 | Choose the booking | Date list appears | ☐ |
| 9.3 | Choose a new date and time | "Appointment rescheduled" | ☐ |
| 9.4 | | **Same booking reference as before** | ☐ |
| 9.5 | Start a new booking for the old time | The **vacated slot is offered again** | ☐ |

---

## Test 10 — Cancel

| # | From Phone B | Expected | ✓ |
|---|--------------|----------|---|
| 10.1 | `Hi` → Book Appointment → **Cancel** | Appointments listed | ☐ |
| 10.2 | Choose one | "Are you sure?" with Yes / No | ☐ |
| 10.3 | Tap **No, Keep It** | "your appointment is unchanged" | ☐ |
| 10.4 | Cancel again, tap **Yes, Cancel** | Cancellation confirmed, refund guidance given | ☐ |
| 10.5 | Start a new booking | The cancelled slot is bookable again | ☐ |
| 10.6 | Open the old payment link in a browser | Page refuses with "no longer awaiting payment" | ☐ |

---

## Test 11 — Robustness

| # | From Phone B | Expected | ✓ |
|---|--------------|----------|---|
| 11.1 | Send `asdfghjkl` mid-flow | Gentle nudge **plus** the current question repeated | ☐ |
| 11.2 | | Never a dead end, never silence | ☐ |
| 11.3 | Send a photo | Bot recovers, re-prompts | ☐ |
| 11.4 | Send an emoji only | Bot recovers | ☐ |
| 11.5 | Enter `X` as your name | "That name looks a little short" | ☐ |
| 11.6 | Enter `123456` as your name | "Please enter your name using letters only" | ☐ |
| 11.7 | Send `Hi` mid-booking | Returns cleanly to the welcome menu | ☐ |
| 11.8 | Wait 35 minutes, then send anything | "Your session timed out" then the welcome menu | ☐ |
| 11.9 | Reach the payment step, wait 16 minutes, tap **I've Paid** | Told the hold expired; offered to book again | ☐ |

---

## Test 12 — Restart and recovery

| # | Action | Expected | ✓ |
|---|--------|----------|---|
| 12.1 | Mid-booking, run restart the fleet (`run_local.ps1`) | Conversation continues from the same step | ☐ |
| 12.2 | `sudo reboot` the VM | Bot comes back automatically, no manual start | ☐ |
| 12.3 | Send `Hi` after reboot | Normal reply | ☐ |
| 12.4 | `Copy-Item data\clinics\<slug>.db backup.db` | A readable copy is produced | ☐ |

---

## Test 13 — Isolation (once a second clinic exists)

| # | Action | Expected | ✓ |
|---|--------|----------|---|
| 13.1 | Message clinic B's number | Clinic **B's** name and services — never clinic A's | ☐ |
| 13.2 | set `enabled: false` for clinic A and restart | Clinic B keeps working normally | ☐ |
| 13.3 | Compare booking references | Prefixes differ per clinic | ☐ |

---

## If something fails

1. The server console (or `logsleet.log`) — the error is almost always here.
2. `curl http://127.0.0.1:<port>/health` — reports missing credentials explicitly.
3. Meta dashboard → WhatsApp → Configuration → Webhook — check for delivery failures.
4. Nothing arriving at all → webhook URL or verify token is wrong.
5. Text arrives but buttons do not render → not a genuine Cloud API business number.

Record the step number, what you saw, and the log lines. That is enough to diagnose.
