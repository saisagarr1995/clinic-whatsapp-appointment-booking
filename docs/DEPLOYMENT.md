# Deployment Guide

From nothing to a live clinic bot, on infrastructure that costs ₹0 per month.

**Time required:** about 90 minutes for the first clinic. Roughly 15 minutes per clinic
after that.

---

## What you are building

```
Patient's WhatsApp
        │
        ▼
   Meta Cloud API
        │  HTTPS webhook
        ▼
  Oracle Always Free VM
        │
    Caddy  ── automatic Let's Encrypt certificate
        │
        ├── /c/smile-dental/*  →  127.0.0.1:8001  →  its own SQLite database
        ├── /c/city-dental/*   →  127.0.0.1:8002  →  its own SQLite database
        └── /c/…                  (one process per clinic, fully isolated)
```

---

## Part 1 — Oracle Cloud VM (about 30 minutes)

### 1.1 Create the account

1. Go to <https://www.oracle.com/cloud/free/> → **Start for free**
2. Choose your country and complete the form.
3. **A credit card is required for identity verification.** Oracle places a temporary
   authorisation (usually about ₹100) and reverses it. **Always Free resources are never
   charged.** Your account cannot become paid unless you explicitly upgrade it.
4. Pick a home region **close to your clinics** — for India, `ap-hyderabad-1` or
   `ap-mumbai-1`. This cannot be changed later.

> If a region reports "out of capacity" for ARM instances, try again at a different hour
> or pick another region. This is common and not a problem with your account.

### 1.2 Create the instance

**Compute → Instances → Create instance**

| Setting | Value |
|---|---|
| Name | `clinic-bot-server` |
| Image | **Ubuntu 24.04** (not Oracle Linux — the scripts assume Ubuntu) |
| Shape | **VM.Standard.A1.Flex** (Ampere ARM) |
| OCPUs | 4 |
| Memory | 24 GB |
| Boot volume | 100 GB |

Confirm the shape is labelled **"Always Free eligible"** before creating.

Under **Add SSH keys**, choose *Generate a key pair* and **download the private key** —
you cannot download it again. Save it somewhere safe on your laptop.

Create the instance and note the **public IP address**.

### 1.3 Open the firewall in Oracle's console

This step is missed constantly and produces a server that looks fine but is unreachable.

**Networking → Virtual Cloud Networks → your VCN → Security Lists → Default Security List
→ Add Ingress Rules**

Add two rules:

| Source CIDR | Protocol | Destination Port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

### 1.4 Connect

```bash
chmod 600 ~/Downloads/ssh-key.key          # macOS/Linux
ssh -i ~/Downloads/ssh-key.key ubuntu@YOUR_PUBLIC_IP
```

On Windows, use PowerShell with the same command, or PuTTY.

---

## Part 2 — Domain name (about 10 minutes)

Meta requires HTTPS with a publicly trusted certificate. That needs a domain name; a bare
IP will not do. DuckDNS provides one free.

1. Go to <https://www.duckdns.org> and sign in with any account.
2. Create a subdomain, e.g. `yourclinic-bot` → `yourclinic-bot.duckdns.org`
3. Set the **current ip** field to your VM's public IP and click **update ip**.
4. Verify from your laptop:

```bash
ping yourclinic-bot.duckdns.org        # must resolve to your VM's IP
```

Wait until it resolves correctly before continuing — Caddy cannot obtain a certificate
otherwise.

---

## Part 3 — Install the software (about 10 minutes)

On the VM:

```bash
curl -fsSL https://raw.githubusercontent.com/saisagarr1995/clinic-whatsapp-appointment-booking/main/deploy/install_server.sh -o install_server.sh

less install_server.sh          # read it before running anything as root

sudo bash install_server.sh
```

This installs Python, Caddy, the application, the systemd units, the `clinic-fleet`
command and a nightly backup job. It is idempotent — safe to re-run.

### Set your domain in both places

```bash
sudo nano /etc/caddy/Caddyfile          # replace bot.example.duckdns.org
sudo nano /opt/clinic-bot/fleet.conf    # DOMAIN=yourclinic-bot.duckdns.org
sudo systemctl reload caddy
```

Confirm the certificate was issued:

```bash
sudo journalctl -u caddy --no-pager | tail -20     # look for "certificate obtained"
curl https://yourclinic-bot.duckdns.org/health     # expect: ok
```

If the certificate fails, DNS is not yet pointing at the VM, or ports 80/443 are not open
in the Oracle console (step 1.3).

---

## Part 4 — Meta WhatsApp setup (about 30 minutes, per clinic)

### 4.1 Create the app

1. <https://developers.facebook.com> → **My Apps → Create App**
2. Use case: **Other** → Type: **Business**
3. Name it after the clinic, then **Create app**.
4. Find **WhatsApp** in the product list → **Set up**.
5. Create or select a Meta Business Account.

### 4.2 Collect credentials

**WhatsApp → API Setup** gives you:

- **Phone number ID** → `WHATSAPP_PHONE_NUMBER_ID`
- **WhatsApp Business Account ID** → `WHATSAPP_BUSINESS_ACCOUNT_ID`
- **Temporary access token** (24 hours — see 4.5 for a permanent one)

**Settings → Basic → App Secret** (click Show) → `WHATSAPP_APP_SECRET`

### 4.3 Add the test recipient

On the same API Setup page, under **To**, add **Phone B** (your test handset). A test
number may message at most 5 whitelisted recipients.

### 4.4 Create the clinic on your server

```bash
sudo clinic-fleet add smile-dental
```

This prints the clinic's **Callback URL** and **Verify Token**. Keep them for the next
step.

Now fill in the details:

```bash
sudo -u clinicbot nano /opt/clinic-bot/clinics/smile-dental/clinic.yaml   # services, doctors, UPI
sudo nano /opt/clinic-bot/clinics/smile-dental/.env                       # Meta credentials
sudo clinic-fleet start smile-dental
sudo clinic-fleet list
```

### 4.5 Configure the webhook

**WhatsApp → Configuration → Edit** on the webhook:

| Field | Value |
|---|---|
| Callback URL | `https://yourclinic-bot.duckdns.org/c/smile-dental/webhook` |
| Verify token | the token printed by `clinic-fleet add` |

Click **Verify and save**. It must succeed immediately — if not, the bot is not running or
the URL is wrong.

Then **Manage** the webhook fields and subscribe to **`messages`**. Without this, nothing
will ever arrive.

### 4.6 Make the access token permanent

The token from API Setup expires in 24 hours. For production:

**Business Settings → Users → System Users → Add** → assign the app with
**Full control** → **Generate new token** → select `whatsapp_business_messaging` and
`whatsapp_business_management` → set expiry to **Never**.

Put that token in the clinic's `.env` and restart:

```bash
sudo clinic-fleet restart smile-dental
```

> **Skipping this is the single most common cause of a bot that "worked yesterday".**

### 4.7 Going live with the clinic's real number

The test number is for testing only. To use the clinic's own number:

**WhatsApp → API Setup → Add phone number**, then verify it by SMS or call.

⚠️ **The number must not be registered in the WhatsApp mobile app.** If the clinic uses it
in WhatsApp or WhatsApp Business today, they must delete that account first
(*Settings → Account → Delete my account*). **This erases their existing chat history**, so
warn them before they do it. Consider a fresh SIM for the bot instead.

---

## Part 5 — Verify

```bash
sudo clinic-fleet list       # active / ok
sudo clinic-fleet logs smile-dental
```

Then work through **[TWO_PHONE_TEST.md](TWO_PHONE_TEST.md)** on real handsets. Do not
consider the clinic live until that passes.

---

## Adding more clinics

```bash
sudo clinic-fleet add city-dental
# edit clinic.yaml and .env, then:
sudo clinic-fleet start city-dental
```

Each clinic needs its **own** Meta app and phone number. Repeat Part 4 for each. Ports are
allocated automatically and the Caddy route is written for you.

---

## Day-to-day operations

```bash
sudo clinic-fleet list                    # everything at a glance
sudo clinic-fleet health                  # health-check every clinic
sudo clinic-fleet logs <slug>             # follow one clinic's logs
sudo clinic-fleet restart <slug>          # restart one clinic
sudo clinic-fleet backup all              # manual backup (runs nightly anyway)
sudo clinic-fleet deploy                  # pull latest main, restart fleet safely
```

`deploy` restarts clinics **one at a time** with a health check between each, so a bad
release cannot take down all 50 at once.

### Backups

Nightly at 02:30, per clinic, verified with `PRAGMA integrity_check`, 30-day retention, in
`/opt/clinic-bot/data/backups/<slug>/`.

```bash
sudo clinic-fleet restore smile-dental /opt/clinic-bot/data/backups/smile-dental/smile-dental-20260803-023000.db.gz
```

Restore preserves the current database first, so the restore itself is reversible.

> **Backups live on the same VM.** If the VM is lost, so are they. Once you have paying
> clinics, copy `/opt/clinic-bot/data/backups/` off the server regularly — `rclone` to any
> free object storage, or `scp` on a schedule from a machine you control.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Webhook verification fails in Meta | Bot not running (`clinic-fleet list`), wrong URL, or wrong verify token |
| Messages arrive, no reply | Wrong app secret → every request fails signature check. Check `clinic-fleet logs`. |
| Nothing arrives at all | The `messages` webhook field is not subscribed (step 4.5) |
| Worked yesterday, dead today | The 24-hour token expired. Do step 4.6. |
| Buttons appear as plain text | Not a real Cloud API business number |
| Certificate fails | DNS not pointing at the VM, or ports 80/443 closed in the Oracle console |
| `health` says degraded | Missing credentials — the endpoint names which ones |
| Bot stops after some days | Check `journalctl -u clinic-bot@<slug>` and free disk with `df -h` |

Health check reports exactly what is missing:

```bash
curl -s http://127.0.0.1:8001/health | python3 -m json.tool
```

---

## Cost summary

| Item | Cost |
|---|---|
| Oracle Always Free VM | ₹0 forever |
| DuckDNS domain | ₹0 |
| Let's Encrypt certificate | ₹0 |
| WhatsApp service conversations | ₹0 (patient-initiated) |
| AI | ₹0 (there is none) |
| **Total** | **₹0/month** |

The only thing that would cost money is sending **business-initiated template messages**
(for example appointment reminders). The bot never does this, by design.
