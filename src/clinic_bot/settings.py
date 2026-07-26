"""Runtime settings loaded from the environment / .env file.

Secrets live here. Clinic-specific *business* data lives in config/clinic.yaml —
never mix the two.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Meta WhatsApp Cloud API ---
    # Fallbacks only: a clinic's own config/secrets/<slug>.env takes precedence.
    # Convenient when running a single clinic; ignored once each clinic has its own.
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_api_version: str = "v21.0"

    # --- Public addressing ---
    public_base_url: str = "http://localhost:8000"

    # --- Local ---
    database_url: str = "sqlite:///data/clinic.db"
    clinic_config_path: str = "config/clinic.yaml"
    #: The fleet definition. Each clinic listed here gets its own config,
    #: its own database file and its own Meta credentials.
    clinics_registry_path: str = "config/clinics.yaml"
    #: Directory holding per-clinic Meta credentials as <slug>.env. Gitignored.
    secrets_dir: str = "config/secrets"
    #: Mounts the offline simulator at /c/{slug}/sim. MUST stay false in
    #: production: the simulator injects messages into the state machine without
    #: a webhook signature, which is exactly what signature verification exists
    #: to prevent. Off by default, and the routes are not registered when off.
    simulator: bool = False
    # Localhost by default. In production Caddy terminates TLS and proxies inward,
    # so the app must never listen on a public interface. Override only if you
    # genuinely intend to expose it unproxied.
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    # Set by the test suite so the app can run without Meta credentials.
    testing: bool = Field(default=False)

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    # Credential URLs and completeness checks live on registry.ClinicCredentials,
    # because they are per clinic. Nothing process-wide should build a Graph URL.


@lru_cache
def get_settings() -> Settings:
    return Settings()
