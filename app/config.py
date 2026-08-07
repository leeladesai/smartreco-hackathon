from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    mesh_api_key: str | None = None
    mesh_base_url: str = "https://api.meshapi.ai/v1"
    mesh_model: str = "tencent/hy3"
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'smartreco.db'}"
    secret_key: str = "change-me-to-a-random-secret"
    chroma_db_path: str = str(PROJECT_ROOT / "chroma_data")
    session_cookie_name: str = "smartreco_session"

    # OBS-1: LangSmith tracing (bonus, optional — off unless an API key is set)
    langsmith_api_key: str | None = None
    langsmith_project: str = "smartreco"

    # DLV-3: scheduled digest (bonus). Email delivers per-user via `User.email`; Telegram
    # is a single broadcast chat (no per-user chat-id mapping exists yet). Neither configured
    # falls back to logging the digest instead of silently dropping it.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    digest_cron_hour: int = 9
    digest_cron_minute: int = 0

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
