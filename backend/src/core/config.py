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
    # NOTE on timeouts: Gemini Flash structured_output responses for the
    # recommender schema can take 10-30s, especially on cold/first calls.
    # Keeping LLM_TIMEOUT_SECONDS too low causes 504 DEADLINE_EXCEEDED and
    # forces the agentic pipeline into its heuristic-fallback path, making
    # the AI engine indistinguishable from the Rank engine in the UI.
    LLM_MODEL: str = "gemini-flash-latest"
    LLM_TEMPERATURE: float = 0.2
    LLM_TIMEOUT_SECONDS: int = 45
    LLM_MAX_RETRIES: int = 2

    # Agentic pipeline runtime guardrails — must stay larger than the worst
    # case (LLM_TIMEOUT_SECONDS * (LLM_MAX_RETRIES + 1)) so the graph wrapper
    # does not trip before the LLM retry budget is exhausted.
    AGENTIC_MAX_RUNTIME_SECONDS: int = 150

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
