from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(v: object) -> object:
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "production"] = "development"

    # Public base URL of this API. It is the "iss" of every access token and
    # the base of the Google redirect URI (<api_base_url>/v1/auth/google/callback).
    api_base_url: str = "http://localhost:8000"

    # Pooled connection string, used by the app.
    database_url: str = ""
    # Direct (non-pooled) connection string, used by Alembic.
    database_url_direct: str = ""

    db_pool_size: int = 5
    db_max_overflow: int = 5
    # Open a fresh connection per request instead of keeping a pool. Safer on
    # serverless hosts (Vercel), where an instance can be frozen between
    # requests and pooled connections go stale. Neon's pooler keeps the
    # actual Postgres connections warm, so the cost is one short TLS handshake.
    db_null_pool: bool = False

    # NoDecode: read a plain comma-separated string, not JSON.
    cors_origins: Annotated[list[str], NoDecode] = []

    # ---- Hasesa Accounts ----
    # RSA private key (PEM) that signs access tokens. Its public half is
    # published at /.well-known/jwks.json. Newlines may be written as "\n".
    jwt_private_key: str = ""
    # Key ID ("kid") of that key. Change it whenever the key changes.
    jwt_key_id: str = "hasesa-1"
    # Secret for refresh tokens (HMAC). At least 32 characters.
    refresh_token_secret: str = ""
    # Secrets of confidential clients, as "client_id:secret,client_id:secret".
    client_secrets: Annotated[dict[str, str], NoDecode] = {}

    # Google OAuth client used for the browser sign-in flow (shared with the web app).
    google_client_id: str = ""
    google_client_secret: str = ""
    # Extra Google client IDs whose ID tokens are accepted (Android, iOS apps).
    google_native_client_ids: Annotated[list[str], NoDecode] = []

    # Emails of the people who run Hasesa (comma-separated). They sign in with
    # Google like everyone else and get the admin tools.
    admin_emails: Annotated[list[str], NoDecode] = []

    # ---- Chapa payments ----
    # Use the CHASECK_TEST-... key on Preview, the live key on Production.
    chapa_secret_key: str = ""
    # The webhook secret set in the Chapa dashboard (falls back to the secret key).
    chapa_webhook_secret: str = ""

    @field_validator("cors_origins", "google_native_client_ids", mode="before")
    @classmethod
    def split_lists(cls, v: object) -> object:
        return _split_csv(v)

    @field_validator("admin_emails", mode="before")
    @classmethod
    def split_emails(cls, v: object) -> object:
        v = _split_csv(v)
        return [e.lower() for e in v] if isinstance(v, list) else v

    @field_validator("client_secrets", mode="before")
    @classmethod
    def parse_client_secrets(cls, v: object) -> object:
        if isinstance(v, str):
            pairs = {}
            for item in _split_csv(v):  # type: ignore[union-attr]
                client_id, sep, secret = item.partition(":")
                if not sep or not client_id or not secret:
                    raise ValueError("CLIENT_SECRETS must look like client_id:secret,client_id:secret")
                pairs[client_id] = secret
            return pairs
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
