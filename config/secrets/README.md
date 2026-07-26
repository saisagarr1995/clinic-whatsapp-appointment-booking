# Per-clinic secrets

One file per clinic, named after its slug: `config/secrets/<slug>.env`.

**Every `*.env` file in this directory is gitignored and must stay that way.**
These files hold Meta access tokens — a leaked token lets anyone send WhatsApp
messages as that clinic.

Create one by copying the template:

```powershell
Copy-Item config\secrets\example.env.template config\secrets\smile.env
```

Then fill in the four required values from
`developers.facebook.com` → your app → WhatsApp → API Setup.

A clinic with missing credentials still starts, still serves its payment page and
still works in the simulator — it just cannot send WhatsApp messages. `/health`
reports exactly which values are absent.

Anything omitted here falls back to the root `.env`, which is convenient when you
are running a single clinic.
