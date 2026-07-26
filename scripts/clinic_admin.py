"""Fleet administration: add, list, seed and check clinics.

Everything here is a data operation on config/clinics.yaml and the per-clinic
files. No code change is ever needed to onboard a clinic.

    python scripts/clinic_admin.py list
    python scripts/clinic_admin.py add ortho-care --name "OrthoCare Dental"
    python scripts/clinic_admin.py seed ortho-care
    python scripts/clinic_admin.py check
    python scripts/clinic_admin.py webhook ortho-care

Payment verification — a booking only becomes CONFIRMED through these:

    python scripts/clinic_admin.py payments ortho-care     # who is waiting
    python scripts/clinic_admin.py confirm  ortho-care SDC-ALE7Y
    python scripts/clinic_admin.py reject   ortho-care SDC-ALE7Y

Run it through the venv interpreter:
    .venv\\Scripts\\python.exe scripts/clinic_admin.py list
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from clinic_bot.clinic_config import ConfigError, load_clinic_config  # noqa: E402
from clinic_bot.db.seed import seed  # noqa: E402
from clinic_bot.registry import (  # noqa: E402
    RegistryError,
    _validate_slug,
    get_registry,
    reset_registry,
)
from clinic_bot.settings import get_settings  # noqa: E402

OK = "  OK  "
BAD = " FAIL "


def _registry_path() -> Path:
    return ROOT / get_settings().clinics_registry_path


def cmd_list(_args: argparse.Namespace) -> int:
    clinics = get_registry()
    print(f"\n{len(clinics)} clinic(s) enabled\n")
    for slug, clinic in clinics.items():
        missing = clinic.credentials.missing()
        creds = "configured" if not missing else f"MISSING {', '.join(missing)}"
        print(f"  {slug}")
        print(f"    name      {clinic.name}")
        print(f"    config    {clinic.config_path}")
        print(f"    database  {clinic.db_url}")
        print(f"    webhook   {clinic.public_base_url}/webhook")
        print(f"    meta      {creds}")
        print()
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    slug = args.slug
    try:
        _validate_slug(slug)
    except RegistryError as exc:
        print(f"{BAD} {exc}")
        return 1

    registry = _registry_path()
    if not registry.exists():
        print(f"{BAD} {registry} does not exist.")
        return 1

    text = registry.read_text(encoding="utf-8")
    if f"slug: {slug}\n" in text:
        print(f"{BAD} clinic {slug!r} is already in {registry.name}")
        return 1

    config_rel = f"config/clinics/{slug}.yaml"
    config_path = ROOT / config_rel
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        print(f"  ..  {config_rel} already exists, keeping it")
    else:
        # Start from the working example so the operator edits real values
        # rather than inventing the file shape from scratch.
        shutil.copy(ROOT / "config" / "clinic.yaml", config_path)
        print(f"{OK} created {config_rel} (edit it with this clinic's real details)")

    name = args.name or slug
    entry = (
        f"\n  - slug: {slug}\n"
        f'    name: "{name}"\n'
        f"    config: {config_rel}\n"
        f"    enabled: true\n"
    )
    registry.write_text(text.rstrip("\n") + "\n" + entry, encoding="utf-8")
    print(f"{OK} registered {slug!r} in {registry.name}")

    # Not named `secrets`: that shadows the stdlib module and makes every static
    # analyser treat the path itself as a credential.
    secrets_path = ROOT / get_settings().secrets_dir / f"{slug}.env"
    if not secrets_path.exists():
        secrets_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "config" / "secrets" / "example.env.template", secrets_path)
        print(f"{OK} created config/secrets/{slug}.env (fill in the Meta credentials)")

    print("\nNext:")
    print(f"  1. Edit {config_rel} — services, doctors, hours, UPI id")
    print(f"  2. Fill in config/secrets/{slug}.env — Meta credentials")
    print(f"  3. python scripts/clinic_admin.py seed {slug}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    reset_registry()
    clinics = get_registry()
    targets = [args.slug] if args.slug else list(clinics)

    for slug in targets:
        clinic = clinics.get(slug)
        if clinic is None:
            print(f"{BAD} unknown clinic {slug!r}")
            return 1
        try:
            cfg = clinic.config
        except ConfigError as exc:
            print(f"{BAD} {slug}: {exc}")
            return 1
        seed(cfg, url=clinic.db_url)
        print(f"{OK} seeded {slug} -> {clinic.db_url}")
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    """Validate every clinic's config without starting the server."""
    reset_registry()
    try:
        clinics = get_registry()
    except RegistryError as exc:
        print(f"{BAD} registry: {exc}")
        return 1

    failed = 0
    for slug, clinic in clinics.items():
        try:
            cfg = load_clinic_config(clinic.config_path)
        except ConfigError as exc:
            print(f"{BAD} {slug}: {exc}\n")
            failed += 1
            continue

        missing = clinic.credentials.missing()
        note = "" if not missing else f"  (cannot send WhatsApp: missing {', '.join(missing)})"
        print(
            f"{OK} {slug}: {cfg.clinic.name} — "
            f"{len(cfg.services)} services, {len(cfg.doctors)} doctors{note}"
        )

    print()
    if failed:
        print(f"{failed} clinic(s) failed validation.")
        return 1
    print("All clinic configs are valid.")
    return 0


# --------------------------------------------------------------------------
# Payment verification — the only path to CONFIRMED
# --------------------------------------------------------------------------


def _resolve_clinic(slug: str):  # noqa: ANN202
    clinic = get_registry().get(slug)
    if clinic is None:
        print(f"{BAD} unknown clinic {slug!r}")
    return clinic


def cmd_payments(args: argparse.Namespace) -> int:
    """List bookings a human still has to check against the bank statement."""
    from clinic_bot.booking_service import pending_verification
    from clinic_bot.scheduling import clock

    clinic = _resolve_clinic(args.slug)
    if clinic is None:
        return 1

    with clinic.session() as db:
        pending = pending_verification(db)
        if not pending:
            print("\nNothing awaiting verification.\n")
            return 0

        now = clock.now()
        print(f"\n{len(pending)} booking(s) awaiting payment verification — oldest first\n")
        print(f"  {'REF':<12} {'AMOUNT':>7}  {'WAITING':>9}  {'UPI REF':<16} PATIENT / APPOINTMENT")
        print("  " + "-" * 88)
        for b in pending:
            waited = now - b.paid_declared_at if b.paid_declared_at else None
            hours = f"{waited.total_seconds() / 3600:.1f}h" if waited else "?"
            utr = b.payment_ref or "(not given)"
            when = b.starts_at.strftime("%a %d %b %H:%M")
            print(
                f"  {b.ref:<12} {b.amount:>7}  {hours:>9}  {utr:<16} "
                f"{b.patient_name} · {b.patient.wa_id} · {when} · {b.doctor.name}"
            )

        print("\nCheck each UPI reference against the clinic's bank/UPI statement, then:")
        print(f"  python scripts/clinic_admin.py confirm {args.slug} <REF>")
        print(f"  python scripts/clinic_admin.py reject  {args.slug} <REF>\n")
        print("A rejected booking frees the slot immediately.\n")
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    from clinic_bot.booking_service import booking_by_ref, confirm_booking

    clinic = _resolve_clinic(args.slug)
    if clinic is None:
        return 1

    with clinic.session() as db:
        booking = booking_by_ref(db, args.ref)
        if booking is None:
            print(f"{BAD} no booking {args.ref!r} at {args.slug}")
            return 1
        try:
            confirm_booking(db, booking, verified_by=args.by)
        except ValueError as exc:
            print(f"{BAD} {exc}")
            return 1
        print(f"{OK} {booking.ref} CONFIRMED for {booking.patient_name} "
              f"({booking.starts_at:%a %d %b %H:%M})")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    from clinic_bot.booking_service import booking_by_ref, reject_payment

    clinic = _resolve_clinic(args.slug)
    if clinic is None:
        return 1

    with clinic.session() as db:
        booking = booking_by_ref(db, args.ref)
        if booking is None:
            print(f"{BAD} no booking {args.ref!r} at {args.slug}")
            return 1
        try:
            reject_payment(db, booking, verified_by=args.by, reason=args.reason)
        except ValueError as exc:
            print(f"{BAD} {exc}")
            return 1
        print(f"{OK} {booking.ref} rejected and CANCELLED — the slot is free again.")
        print("     Call the patient if they believe they did pay: "
              f"{booking.patient.wa_id}")
    return 0


def cmd_webhook(args: argparse.Namespace) -> int:
    """Print exactly what to paste into the Meta dashboard."""
    clinics = get_registry()
    clinic = clinics.get(args.slug)
    if clinic is None:
        print(f"{BAD} unknown clinic {args.slug!r}")
        return 1

    token = clinic.credentials.verify_token or "(not set — add WHATSAPP_VERIFY_TOKEN)"
    print("\nMeta dashboard -> WhatsApp -> Configuration -> Edit webhook\n")
    print(f"  Callback URL   {clinic.public_base_url}/webhook")
    print(f"  Verify token   {token}")
    print("\nThen subscribe to the 'messages' field.\n")

    if not get_settings().public_base_url.startswith("https://"):
        print("WARNING: PUBLIC_BASE_URL is not https — Meta will refuse this webhook.")
        print("Start your tunnel and set PUBLIC_BASE_URL in .env to its https address.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="clinic_admin",
        description="Manage the clinic fleet defined in config/clinics.yaml",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show every enabled clinic").set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="register a new clinic")
    p_add.add_argument("slug", help="lowercase url-safe id, e.g. ortho-care")
    p_add.add_argument("--name", help="display name")
    p_add.set_defaults(func=cmd_add)

    p_seed = sub.add_parser("seed", help="create/refresh a clinic's database")
    p_seed.add_argument("slug", nargs="?", help="omit to seed every clinic")
    p_seed.set_defaults(func=cmd_seed)

    sub.add_parser("check", help="validate every clinic config").set_defaults(func=cmd_check)

    p_pay = sub.add_parser("payments", help="list bookings awaiting payment verification")
    p_pay.add_argument("slug")
    p_pay.set_defaults(func=cmd_payments)

    p_conf = sub.add_parser("confirm", help="mark a payment as received")
    p_conf.add_argument("slug")
    p_conf.add_argument("ref", help="booking reference, e.g. SDC-ALE7Y")
    p_conf.add_argument("--by", default="staff", help="who verified it")
    p_conf.set_defaults(func=cmd_confirm)

    p_rej = sub.add_parser("reject", help="payment not found — cancel and free the slot")
    p_rej.add_argument("slug")
    p_rej.add_argument("ref")
    p_rej.add_argument("--by", default="staff")
    p_rej.add_argument("--reason", default="payment not received")
    p_rej.set_defaults(func=cmd_reject)

    p_hook = sub.add_parser("webhook", help="print the Meta webhook settings")
    p_hook.add_argument("slug")
    p_hook.set_defaults(func=cmd_webhook)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
