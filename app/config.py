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

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
