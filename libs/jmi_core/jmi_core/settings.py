"""Centralized configuration via pydantic-settings.

Secrets are read from their conventional, *unprefixed* env var names so the
underlying tools (MotherDuck, optional cloud LLMs) pick them up too; app-level
config is ``JMI_``-prefixed. Values come from the environment or a local
``.env`` file.

The default stack is 0€: MotherDuck free tier + local Ollama + free public job
APIs. No keys required beyond the MotherDuck token.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- secrets (conventional env names) --------------------------------
    motherduck_token: str | None = Field(default=None, validation_alias="motherduck_token")
    # Optional cloud LLM keys (only needed if you switch provider off Ollama).
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    # Min seconds between Gemini calls — proactively stays under the free-tier
    # requests-per-minute cap so we don't waste retries / drop postings.
    gemini_min_interval_s: float = Field(default=7.0, validation_alias="JMI_GEMINI_MIN_INTERVAL_S")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    # Optional improvement-section sources.
    scrapfly_key: str | None = Field(default=None, validation_alias="SCRAPFLY_KEY")
    adzuna_app_id: str | None = Field(default=None, validation_alias="ADZUNA_APP_ID")
    adzuna_app_key: str | None = Field(default=None, validation_alias="ADZUNA_APP_KEY")

    # --- warehouse -------------------------------------------------------
    # "md:<db>" => MotherDuck; a filesystem path => local DuckDB (dev/CI).
    duckdb_database: str = Field(
        default="md:job-market-intelligence", validation_alias="JMI_DUCKDB_DATABASE"
    )

    # --- LLM enrichment (default: local Ollama, 0€) ----------------------
    llm_provider: str = Field(
        default="ollama", validation_alias="JMI_LLM_PROVIDER"
    )  # ollama|gemini|anthropic
    llm_model: str = Field(default="qwen2.5:7b", validation_alias="JMI_LLM_MODEL")
    ollama_host: str = Field(default="http://localhost:11434", validation_alias="JMI_OLLAMA_HOST")
    # Cap CPU threads so local inference doesn't peg the laptop (heat/throttle).
    # 0 = let Ollama use every core; 6 ≈ the performance cores on a laptop chip.
    ollama_num_thread: int = Field(default=6, validation_alias="JMI_OLLAMA_NUM_THREAD")
    # How long Ollama keeps the model in RAM after a request: "0" unloads at once,
    # "5m" keeps it warm across a batch, "-1" never unloads.
    ollama_keep_alive: str = Field(default="5m", validation_alias="JMI_OLLAMA_KEEP_ALIVE")
    enrichment_prompt_version: str = Field(
        default="enrich/v1", validation_alias="JMI_ENRICHMENT_PROMPT_VERSION"
    )
    enrichment_batch_size: int = Field(default=50, validation_alias="JMI_ENRICHMENT_BATCH_SIZE")

    # --- scraping --------------------------------------------------------
    scrape_max_postings: int = Field(default=200, validation_alias="JMI_SCRAPE_MAX_POSTINGS")

    # --- logging ---------------------------------------------------------
    log_level: str = Field(default="INFO", validation_alias="JMI_LOG_LEVEL")
    log_json: bool = Field(default=False, validation_alias="JMI_LOG_JSON")

    @property
    def is_motherduck(self) -> bool:
        return self.duckdb_database.startswith("md:")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide singleton. Call this instead of constructing ``Settings``."""
    return Settings()
