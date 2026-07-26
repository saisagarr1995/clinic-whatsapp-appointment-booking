"""The clinic fleet registry.

One laptop (or one VM) serves many clinics from a single process. This module is
the only place that knows the fleet exists; everything downstream is handed a
single `Clinic` and behaves exactly as the original single-clinic code did.

Layout
------
    config/clinics.yaml            the registry — add a clinic here, no code change
    config/clinics/<slug>.yaml     that clinic's services, doctors, hours, UPI
    config/secrets/<slug>.env      that clinic's Meta credentials (GITIGNORED)
    data/clinics/<slug>.db         that clinic's database

Isolation
---------
Each clinic gets its own SQLite file and its own Meta app secret. A webhook
signature valid for one clinic is rejected by every other, and a booking
reference from one clinic is simply absent from another's database. There is no
shared table and therefore no `WHERE clinic_id` to forget.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from clinic_bot.clinic_config import ClinicConfig, ConfigError, load_clinic_config
from clinic_bot.db.session import init_db, session_scope
from clinic_bot.settings import Settings, get_settings

log = logging.getLogger(__name__)

#: Slugs become URL path segments and filenames, so keep them boring.
_SLUG_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-")


class RegistryError(RuntimeError):
    """clinics.yaml is missing or invalid."""


class UnknownClinicError(KeyError):
    """No enabled clinic with that slug."""


def _validate_slug(slug: str) -> str:
    """Reject anything that is not already a clean slug.

    Deliberately does NOT silently lowercase or rewrite: the slug is copied by
    hand into the Meta webhook URL, so what the operator reads in clinics.yaml
    must be exactly what the server serves.
    """
    if not slug or not set(slug) <= _SLUG_OK:
        raise RegistryError(
            f"clinic slug {slug!r} is invalid: use lowercase letters, digits and "
            f"hyphens only (it becomes a URL path and a filename)"
        )
    return slug


def _read_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser.

    Deliberately stdlib-only: python-dotenv is not a declared dependency of this
    project and must not become one for eight lines of parsing.
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip().upper()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class ClinicCredentials:
    """One clinic's Meta WhatsApp Cloud API credentials."""

    phone_number_id: str = ""
    access_token: str = ""
    app_secret: str = ""
    verify_token: str = ""
    api_version: str = "v21.0"

    @property
    def messages_url(self) -> str:
        return (
            f"https://graph.facebook.com/{self.api_version}"
            f"/{self.phone_number_id}/messages"
        )

    def missing(self) -> list[str]:
        """Credential names that must be set before this clinic can go live."""
        required = {
            "WHATSAPP_PHONE_NUMBER_ID": self.phone_number_id,
            "WHATSAPP_ACCESS_TOKEN": self.access_token,
            "WHATSAPP_APP_SECRET": self.app_secret,
            "WHATSAPP_VERIFY_TOKEN": self.verify_token,
        }
        return [name for name, value in required.items() if not value.strip()]

    @property
    def configured(self) -> bool:
        return not self.missing()


@dataclass
class Clinic:
    """One clinic in the fleet, with everything needed to serve it."""

    slug: str
    name: str
    config_path: Path
    db_url: str
    credentials: ClinicCredentials
    public_base_url: str
    enabled: bool = True
    _config: ClinicConfig | None = field(default=None, repr=False)

    @property
    def config(self) -> ClinicConfig:
        """Parsed clinic.yaml. Loaded once, on first use."""
        if self._config is None:
            self._config = load_clinic_config(self.config_path)
        return self._config

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A transactional session against THIS clinic's database."""
        with session_scope(self.db_url) as db:
            yield db

    def init_db(self) -> None:
        init_db(self.db_url)

    def router(self):  # noqa: ANN201 - avoids a circular import at module scope
        from clinic_bot.flow.router import Router

        return Router(self.config, get_settings(), base_url=self.public_base_url)


def _clinic_from_entry(entry: dict, settings: Settings, index: int) -> Clinic:
    if not isinstance(entry, dict):
        raise RegistryError(f"clinics[{index}] must be a mapping, got {type(entry).__name__}")

    slug = _validate_slug(str(entry.get("slug", "")).strip())
    name = str(entry.get("name") or slug).strip()

    config_path = Path(entry.get("config") or f"config/clinics/{slug}.yaml")

    db_value = entry.get("database")
    db_url = str(db_value) if db_value else f"sqlite:///data/clinics/{slug}.db"

    # Secrets file wins; anything it omits falls back to the global .env so a
    # single-clinic setup keeps working exactly as before.
    secrets = _read_env_file(Path(settings.secrets_dir) / f"{slug}.env")
    creds = ClinicCredentials(
        phone_number_id=secrets.get("WHATSAPP_PHONE_NUMBER_ID", settings.whatsapp_phone_number_id),
        access_token=secrets.get("WHATSAPP_ACCESS_TOKEN", settings.whatsapp_access_token),
        app_secret=secrets.get("WHATSAPP_APP_SECRET", settings.whatsapp_app_secret),
        verify_token=secrets.get("WHATSAPP_VERIFY_TOKEN", settings.whatsapp_verify_token),
        api_version=secrets.get("WHATSAPP_API_VERSION", settings.whatsapp_api_version),
    )

    return Clinic(
        slug=slug,
        name=name,
        config_path=config_path,
        db_url=db_url,
        credentials=creds,
        public_base_url=f"{settings.public_base_url.rstrip('/')}/c/{slug}",
        enabled=bool(entry.get("enabled", True)),
    )


def load_registry(path: str | Path | None = None) -> dict[str, Clinic]:
    """Parse clinics.yaml into slug -> Clinic. Disabled clinics are excluded."""
    settings = get_settings()
    p = Path(path or settings.clinics_registry_path)

    if not p.exists():
        raise RegistryError(
            f"Clinic registry not found at {p}.\n"
            f"Create it with:  .venv\\Scripts\\python.exe scripts/clinic_admin.py add <slug>"
        )

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RegistryError(f"{p} is not valid YAML:\n{exc}") from exc

    if not isinstance(raw, dict) or "clinics" not in raw:
        raise RegistryError(f"{p} must be a mapping with a top-level `clinics:` list.")

    entries = raw.get("clinics") or []
    if not isinstance(entries, list) or not entries:
        raise RegistryError(f"{p} lists no clinics. Add at least one.")

    clinics: dict[str, Clinic] = {}
    for index, entry in enumerate(entries):
        clinic = _clinic_from_entry(entry, settings, index)
        if clinic.slug in clinics:
            raise RegistryError(f"duplicate clinic slug {clinic.slug!r} in {p}")
        if not clinic.enabled:
            log.info("Clinic %s is disabled — skipping", clinic.slug)
            continue
        clinics[clinic.slug] = clinic

    if not clinics:
        raise RegistryError(f"{p} has clinics, but every one of them is disabled.")
    return clinics


def _assert_one_timezone(clinics: dict[str, Clinic]) -> None:
    """Refuse to serve clinics in different timezones from one process.

    `scheduling.clock` is process-wide: it resolves "now" once, from the default
    clinic config. If two clinics disagreed on their timezone, one of them would
    silently get slot times, min-notice windows and hold expiry computed in the
    other's local time — wrong appointments, with nothing visibly failing.

    Failing loudly here is the cheap correct answer. Making `clock` per clinic is
    the expensive one, and is only worth doing if this limit is ever hit.
    """
    zones: dict[str, list[str]] = {}
    for slug, clinic in clinics.items():
        try:
            tz = clinic.config.clinic.timezone
        except ConfigError:
            continue  # validate_all() reports config errors with better context
        zones.setdefault(tz, []).append(slug)

    if len(zones) > 1:
        detail = "; ".join(f"{tz}: {', '.join(sorted(s))}" for tz, s in sorted(zones.items()))
        raise RegistryError(
            "clinics in this fleet disagree on their timezone, and one process "
            "cannot serve both correctly — appointment times would be wrong for "
            f"one of them.\n  {detail}\n"
            "Give every clinic the same `clinic.timezone`, or run a second "
            "instance with its own registry for the other timezone."
        )


# --------------------------------------------------------------------------
# Process-wide cache
# --------------------------------------------------------------------------

_registry: dict[str, Clinic] | None = None


def get_registry() -> dict[str, Clinic]:
    global _registry
    if _registry is None:
        _registry = load_registry()
    return _registry


def reset_registry() -> None:
    """Drop the cached registry. Used by tests and by a config reload."""
    global _registry
    _registry = None


def get_clinic(slug: str) -> Clinic:
    try:
        return get_registry()[slug]
    except KeyError as exc:
        raise UnknownClinicError(slug) from exc


def validate_all() -> list[tuple[str, str]]:
    """Load every clinic's config up front. Returns [(slug, error)] for failures.

    Called at startup so a broken clinic.yaml is reported when the operator can
    still fix it, rather than when a patient sends the first message.
    """
    clinics = get_registry()
    problems: list[tuple[str, str]] = []
    for slug, clinic in clinics.items():
        try:
            _ = clinic.config  # property access performs the load
        except ConfigError as exc:
            problems.append((slug, str(exc)))

    # Only meaningful once the configs above have loaded.
    if not problems:
        _assert_one_timezone(clinics)
    return problems


# --------------------------------------------------------------------------
# FastAPI wiring
# --------------------------------------------------------------------------


def clinic_dependency(slug: str) -> Clinic:
    """Resolve the {slug} path parameter to a Clinic, or 404."""
    from fastapi import HTTPException

    try:
        return get_clinic(slug)
    except UnknownClinicError as exc:
        raise HTTPException(status_code=404, detail="Unknown clinic") from exc
