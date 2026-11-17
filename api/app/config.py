"""Settings for the API, read from environment variables (and api/.env in development).

Why pydantic-settings instead of os.environ? It reads every setting in one place, converts
types, and fails at start-up with a clear message if a value is wrong, instead of failing
later in the middle of a request.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    # Reads api/.env if it exists. Real environment variables win over the file, which is
    # how a hosting service supplies them. Unknown keys in .env are ignored.
    model_config = SettingsConfigDict(
        env_file=API_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    #: Sites allowed to call the API from a browser, comma-separated in the env variable.
    cors_origins: str = "http://localhost:3000"

    #: SQLAlchemy connection string for the Supabase Postgres. NEVER commit or print this.
    database_url: str | None = None

    #: Shared secret the Next.js server sends in the X-API-Key header. When it is empty the
    #: API is open, which is only acceptable on your own computer.
    api_shared_secret: str | None = None

    #: Folder for stored signal files (gitignored). A relative path is relative to api/.
    file_store_dir: Path = Path("file_store")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def file_store_path(self) -> Path:
        d = self.file_store_dir
        return d if d.is_absolute() else API_DIR / d


@lru_cache
def get_settings() -> Settings:
    """The settings, read once and reused (lru_cache remembers the first result)."""
    return Settings()
