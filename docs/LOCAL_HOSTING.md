# Running the clinic fleet on your laptop

This is the runbook for hosting the bot on a Windows laptop instead of the Oracle
VM. Everything here is free and open source.

**Read the honest limits at the bottom before putting a paying clinic on this.**

---

## 0. What you have

| Thing | Where |
|---|---|
| Fleet registry — **the file you edit to add a clinic** | `config/clinics.yaml` |
| A clinic's services, doctors, hours, UPI | `config/clinics/<slug>.yaml` |
| A clinic's Meta credentials (gitignored) | `config/secrets/<slug>.env` |
| A clinic's database | `data/clinics/<slug>.db` |
| Fleet admin CLI | `scripts/clinic_admin.py` |
| **Verify payments (daily job)** | `clinic_admin.py payments / confirm / reject` — §4a |
| Start the fleet | `scripts/run_local.ps1` |
| Auto-start at logon | `scripts/install_autostart.ps1` |

One process serves every clinic. Measured cost: **85 MB for one clinic, 87 MB for
five** — roughly 0.4 MB per extra clinic, because only the SQLite handles and the
parsed config differ.

---

## 1. Start it (no Meta account needed)

```powershell
.\scripts\run_local.ps1
```

Then open the simulator:

```
http://127.0.0.1:8000/c/smile/sim
```

That page drives the **real** state machine against the **real** database. Every
button and list row carries the same id that goes over the wire to WhatsApp, so
what you validate here is what a patient gets. Bookings you make are real
bookings — that is deliberate, since it lets you catch double-booking bugs.

Check the fleet at any time:

```
http://127.0.0.1:8000/health
```

---

## 2. Add a clinic

```powershell
.venv\Scripts\python.exe scripts\clinic_admin.py add ortho-care --name "OrthoCare Dental"
```

That creates `config/clinics/ortho-care.yaml`, registers it in `config/clinics.yaml`,
and creates an empty `config/secrets/ortho-care.env`.

Then:

1. Edit `config/clinics/ortho-care.yaml` — services, doctors, hours, UPI id.
2. Seed it: `.venv\Scripts\python.exe scripts\clinic_admin.py seed ortho-care`
3. Restart the fleet.

Useful commands:

```powershell
.venv\Scripts\python.exe scripts\clinic_admin.py list      # every clinic + its webhook URL
.venv\Scripts\python.exe scripts\clinic_admin.py check     # validate all configs
.venv\Scripts\python.exe scripts\clinic_admin.py webhook ortho-care
```

> **The slug is permanent.** It appears in the webhook URL you register with Meta
> and in payment links already sitting in patients' chats. Changing it later
> breaks both.

---

## 3. Go live: a public HTTPS address with Tailscale Funnel

Meta will only deliver webhooks to a public HTTPS URL with a valid certificate.
Tailscale Funnel provides one, free, with no domain and no card. The address is
**stable across reboots**, which matters because the webhook URL is registered
with Meta once.

1. Install Tailscale: <https://tailscale.com/download/windows> — sign in with any
   Google/GitHub account. The client is open source (BSD-3).

2. Enable HTTPS and Funnel once, in the admin console
   (<https://login.tailscale.com/admin/dns>): turn on **MagicDNS** and
   **HTTPS Certificates**.

3. Point Funnel at the local port:

   ```powershell
   tailscale funnel 8000
   ```

   It prints your public address, e.g.
   `https://your-pc.tailXXXX.ts.net`

4. Put that in `.env` — **no trailing slash, no `/c/<slug>` suffix**, the app adds
   the clinic prefix itself:

   ```
   PUBLIC_BASE_URL=https://your-pc.tailXXXX.ts.net
   ```

5. **Turn the simulator off** before the address is public:

   ```
   SIMULATOR=false
   ```

6. Restart the fleet.

To run Funnel permanently in the background:

```powershell
tailscale funnel --bg 8000
```

---

## 4. Connect a clinic to WhatsApp

For each clinic, at <https://developers.facebook.com>:

1. Create an app → add the **WhatsApp** product.
2. From **API Setup**, copy the phone number id and a token.
3. From **Settings → Basic**, copy the App Secret.
4. Invent a verify token:
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`
5. Put all four into `config/secrets/<slug>.env`.
6. Print the exact values to paste back into Meta:

   ```powershell
   .venv\Scripts\python.exe scripts\clinic_admin.py webhook <slug>
   ```

7. In Meta: **WhatsApp → Configuration → Edit webhook**, paste the callback URL and
   verify token, save, then subscribe to the **messages** field.
8. Restart the fleet and confirm `/health` shows `can_send_whatsapp: true`.

While testing, Meta's free test number allows up to 5 whitelisted recipients, so
you can message the bot from your own phone before touching a clinic's real number.

> Registering a real business number on the Cloud API **erases that number's
> existing WhatsApp chat history** and it can no longer be used in the WhatsApp
> mobile app. Use a fresh SIM if the number is in daily use.

---

## 4a. Verifying payments — the daily job

**The bot cannot tell whether a patient actually paid.** UPI here is peer-to-peer with
no gateway, so nothing in this software sees money arrive. "I've Paid" is a *claim*.

After tapping it the patient is asked for their **UPI reference number (UTR)**, and the
booking sits in `AWAITING_VERIFICATION` until a human decides.

Someone at the clinic must do this, ideally once or twice a day:

```powershell
.venv\Scripts\python.exe scripts\clinic_admin.py payments smile
```

```
  REF          AMOUNT   WAITING  UPI REF        PATIENT / APPOINTMENT
  SDC-CVPYA       200      0.4h  438291750163   Sagar R · 919000000001 · Mon 27 Jul 09:00
```

Compare each UPI reference against the clinic's bank or UPI app statement, then:

```powershell
.venv\Scripts\python.exe scripts\clinic_admin.py confirm smile SDC-CVPYA --by priya
.venv\Scripts\python.exe scripts\clinic_admin.py reject  smile SDC-CVPYA --reason "no credit found"
```

- **confirm** → `CONFIRMED`. This is the only way a booking ever becomes confirmed.
- **reject** → `CANCELLED`, and **the slot is immediately free** for someone else.

### Two things to understand

**An unverified claim keeps its slot and never expires by itself.** That is deliberate —
a patient who really paid must not lose their appointment to a timer. The cost is that a
false claim blocks that slot until someone reviews it. The `WAITING` column exists so
those stand out; anything above a few hours deserves a look.

**The bot never tells the patient they are confirmed.** It says the payment is *being
verified*. If you want the patient told once you confirm, that needs a WhatsApp template
message, which Meta charges for — it would break the ₹0 guarantee, so it is deliberately
not done. Phone them instead.

---

## 5. Keep it running

```powershell
.\scripts\install_autostart.ps1          # start at logon, restart on crash
.\scripts\install_autostart.ps1 -Status
.\scripts\install_autostart.ps1 -Remove
```

**Sleep is what will actually kill your bot.** The script does not change your
power settings, because that affects your whole machine. If patients must be able
to book at any hour, run these yourself in an **admin** PowerShell:

```powershell
powercfg /change standby-timeout-ac 0     # never sleep on mains
powercfg /change hibernate-timeout-ac 0   # never hibernate
powercfg /change monitor-timeout-ac 10    # screen off is fine
```

Closing the lid still sleeps the laptop by default:
**Control Panel → Power Options → Choose what closing the lid does**.

### Backups

The databases are just files. Copy them somewhere off the laptop regularly:

```powershell
Copy-Item data\clinics\*.db "$env:USERPROFILE\OneDrive\clinic-backups\"
```

A backup on the same laptop as the data is not a backup.

---

## 6. Honest limits of laptop hosting

The code is identical whether it runs here or on the Oracle VM. The difference is
availability, and it is not small:

| Risk | Effect | Mitigation |
|---|---|---|
| Windows Update reboots | Bot down until you log in | Task Scheduler restarts at logon |
| Laptop sleeps / lid closed | **Every clinic offline** | `powercfg` above |
| Power or internet cut | Bot down; Meta retries a few hours then drops the message | None |
| Laptop is also your daily machine | Accidental shutdown | None |

For **validating, demoing and running your own first clinic**, this is fine. For
several clinics whose patients depend on it, move to an always-on server. Migration is
copying `data/clinics/*.db` across, because nothing else differs — the application code
is identical. `deploy/Caddyfile` is ready for that; the systemd unit would need writing
as one unit for the whole fleet (the old per-clinic template was removed in CAB-0015).

---

## 7. Troubleshooting

| Symptom | Cause |
|---|---|
| `Clinic registry not found` | Running from the wrong directory — `cd` to the repo root |
| `/health` shows `missing_credentials` | `config/secrets/<slug>.env` is empty or absent |
| Meta rejects the webhook | `PUBLIC_BASE_URL` is not `https://`, or Funnel is not running |
| Simulator returns 404 | `SIMULATOR=false` in `.env` — that is the safe default |
| `timezone ... is not available on this machine` | Install the IANA database: `.venv\Scripts\python.exe -m pip install tzdata` |
| Slots appear at the wrong time | Check `clinic.timezone` in the clinic's YAML, then re-run `clinic_admin.py check` |
| A booking never becomes CONFIRMED | Expected — only `clinic_admin.py confirm` does that. See §4a |
| Buttons do nothing in the simulator | Check the server console; the reply id is logged on error |
| Port 8000 already in use | `Get-NetTCPConnection -LocalPort 8000 -State Listen` |
