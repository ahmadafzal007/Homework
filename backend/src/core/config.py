"""
Application settings loaded from the .env file.
"""
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    GEMINI_API_KEY: str
    MongoDB_URI: str | None = None

    # Dashboard login (supports legacy typo `emial` from .env)
    LOGIN_EMAIL: str = Field(validation_alias=AliasChoices("LOGIN_EMAIL", "emial"))
    LOGIN_PASSWORD: str = Field(validation_alias=AliasChoices("LOGIN_PASSWORD", "password"))
    JWT_SECRET: str
    JWT_EXPIRE_DAYS: int = 15

    # LLM config
    LLM_MODEL: str = "gemini-flash-latest"
    LLM_TEMPERATURE: float = 0.2
    LLM_TIMEOUT_SECONDS: int = 12
    LLM_MAX_RETRIES: int = 1

    # Agentic pipeline runtime guardrails
    AGENTIC_MAX_RUNTIME_SECONDS: int = 30

    # MongoDB config
    MONGODB_DB_NAME: str = "nba_engine"
    MONGODB_COLLECTION_NAME: str = "customers"
    MONGODB_CONNECT_TIMEOUT_MS: int = 5000

    # Server config
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # Submission helper endpoints (used by the frontend dashboard)
    ENABLE_TEST_RUNNER: bool = True
    TEST_RUNNER_TIMEOUT_SECONDS: int = 60


settings = Settings()
