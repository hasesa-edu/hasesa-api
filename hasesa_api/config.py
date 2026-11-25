from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "production"] = "development"

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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
