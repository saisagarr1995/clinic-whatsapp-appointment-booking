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
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_api_version: str = "v21.0"

    # --- Public addressing ---
    public_base_url: str = "http://localhost:8000"

    # --- Local ---
    database_url: str = "sqlite:///data/clinic.db"
    clinic_config_path: str = "config/clinic.yaml"
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

    @property
    def graph_url(self) -> str:
        return f"https://graph.facebook.com/{self.whatsapp_api_version}"

    @property
    def messages_url(self) -> str:
        return f"{self.graph_url}/{self.whatsapp_phone_number_id}/messages"

    def missing_credentials(self) -> list[str]:
        """Return the names of credentials that are required to talk to Meta but unset.

        Used by setup.py and the /health endpoint so a misconfiguration surfaces at
        setup time rather than when the first patient messages.
        """
        required = {
            "WHATSAPP_PHONE_NUMBER_ID": self.whatsapp_phone_number_id,
            "WHATSAPP_ACCESS_TOKEN": self.whatsapp_access_token,
            "WHATSAPP_APP_SECRET": self.whatsapp_app_secret,
            "WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_token,
        }
        return [name for name, value in required.items() if not value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
