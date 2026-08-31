"""
Centralized application settings, loaded from environment variables (.env).
Using pydantic-settings means every config value is TYPED and VALIDATED at
startup -- if a required variable is missing or malformed, the app fails to
boot immediately with a clear error, rather than failing later mid-request
in a way that's hard to trace. This is a deliberate production-safety choice.
"""
from functools import lru_cache
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",  # backend/app/core -> project root .env
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ==== Project ====
    PROJECT_NAME: str = "medstt"
    ENVIRONMENT: str = "development"

    # ==== Postgres ====
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int = 5432
    POSTGRES_HOST: str = "postgres"

    # ==== Redis ====
    REDIS_PORT: int = 6379
    REDIS_HOST: str = "redis"
    REDIS_PASSWORD: str
    
    # ==== Audio storage & ingestion  ====
    AUDIO_STORAGE_ROOT: str = "../storage/audio"  # relative to backend/ working dir
    MAX_UPLOAD_SIZE_BYTES: int = 100 * 1024 * 1024  # 100MB
    ALLOWED_AUDIO_MIME_TYPES: str = (
        "audio/wav,audio/x-wav,audio/mpeg,audio/mp4,audio/m4a,"
        "audio/webm,audio/ogg,audio/flac"
    )
    
    # ==== Hugging Face ====
    HUGGINGFACE_TOKEN: str
    
    # ==== Azure AI Speech (Phase 11: cloud ASR, always-run-both design) ====
    # Optional, not required -- unlike HUGGINGFACE_TOKEN (Phase 8), the
    # system must be able to run with Azure entirely unconfigured, since
    # it's a paid external service the user may want to disable for cost
    # control. is_azure_configured() in azure_asr_service.py is the
    # single source of truth calling code should check.
    AZURE_SPEECH_KEY: str = ""
    AZURE_SPEECH_REGION: str = ""

    # ==== Local PII masking middleware ====
    # MedGemma must only receive tokenized prompts. If the privacy boundary
    # cannot be reached, the draft request fails closed by default.
    PII_MASKING_ENABLED: bool = True
    PII_MASKING_REQUIRED: bool = True
    # Port 8001 deliberately avoids MedScribe's FastAPI backend on 8000.
    PII_MASKING_URL: str = "http://127.0.0.1:8001"
    PII_MASKING_API_KEY: str = "dev-only-key"
    PII_MASKING_TIMEOUT_SECONDS: float = 5.0
    
        # ==== CORS (Phase 16 hardening) ====
    # Comma-separated list, environment-driven -- was hardcoded to
    # localhost:5173 only since Phase 3. Dev default preserves existing
    # behavior; a real deployment sets this via .env to the actual
    # production frontend origin(s), never "*" for a system handling
    # patient data with credentialed (cookie-based) requests.
    CORS_ALLOWED_ORIGINS: str = "http://localhost:5173"
    
    # ==== Cookie security (Phase 16 hardening) ====
    # False in dev (HTTP localhost), MUST be True in any real deployment
    # behind HTTPS -- browsers will not send a secure cookie over plain
    # HTTP, so flipping this on prematurely (before HTTPS is actually in
    # place) would silently break login entirely, not just be "more
    # secure" -- hence a real settable flag, not a hardcoded True.
    COOKIE_SECURE: bool = False
    
     # ==== Rate limiting (Phase 16 hardening) ====
    RATE_LIMIT_LOGIN: str = "10/minute"  # per-IP, deliberately generous vs account lockout's stricter 5-attempt threshold
    RATE_LIMIT_DEFAULT: str = "100/minute"  # general API baseline

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]

    @computed_field
    @property
    def allowed_audio_mime_types_list(self) -> list[str]:
        return [t.strip() for t in self.ALLOWED_AUDIO_MIME_TYPES.split(",")]

    @property
    def audio_originals_path(self) -> str:
        return f"{self.AUDIO_STORAGE_ROOT}/originals"

    @property
    def audio_normalized_path(self) -> str:
        return f"{self.AUDIO_STORAGE_ROOT}/normalized"

    @property
    def DATABASE_URL_ASYNC(self) -> str:
        """Async connection string, used by the FastAPI app at runtime (asyncpg driver)."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@localhost:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Sync connection string, used only by Alembic's migration runner."""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@localhost:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@localhost:{self.REDIS_PORT}/0"


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings instance -- .env is read from disk only once per process,
    not on every request. Safe because config doesn't change at runtime.
    """
    return Settings()
