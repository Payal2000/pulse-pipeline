"""Environment-driven settings for PulsePipe."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Gemini model
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    # Google Cloud
    gcp_project: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", ""))

    # Fivetran
    fivetran_api_key: str = field(default_factory=lambda: os.getenv("FIVETRAN_API_KEY", ""))
    fivetran_api_secret: str = field(default_factory=lambda: os.getenv("FIVETRAN_API_SECRET", ""))

    # BigQuery
    bigquery_dataset: str = field(default_factory=lambda: os.getenv("BIGQUERY_DATASET", "pulse_pipeline"))

    # Webhook
    webhook_url: str = field(default_factory=lambda: os.getenv("WEBHOOK_URL", ""))

    # Server
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8080")))


settings = Settings()
