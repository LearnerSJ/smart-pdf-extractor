"""Application configuration via Pydantic BaseSettings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Central configuration for the PDF Ingestion Layer.
    All values can be overridden via environment variables.
    """

    # AWS / Bedrock
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-6"
    bedrock_fallback_model_id: str | None = None  # e.g., "us.anthropic.claude-haiku-4"
    vlm_confidence_threshold: float = 0.80

    # Triangulation thresholds
    triangulation_soft_flag_threshold: float = 0.10
    triangulation_hard_flag_threshold: float = 0.40

    # Services
    paddleocr_endpoint: str = "http://paddleocr:8080"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pdf_ingestion"

    # Extraction
    digital_page_threshold: float = 0.80
    vlm_verifier_fuzzy_threshold: float = 0.85

    # Chunked VLM extraction
    vlm_max_tokens_per_job: int = 100_000
    vlm_budget_exceeded_action: str = "flag"
    vlm_window_size: int = 12
    vlm_window_overlap: int = 3
    vlm_max_concurrent_windows: int = 3

    # File limits
    max_file_size_mb: int = 50

    # Admin Dashboard - JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 8

    # Admin Dashboard - Token cost rates (per 1k tokens)
    token_cost_per_1k_input: float = 0.003
    token_cost_per_1k_output: float = 0.015

    # Admin Dashboard - Alert engine
    alert_evaluation_interval_seconds: int = 60

    # Admin Dashboard - SMTP (for email notifications)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_from: str = "alerts@pdf-ingestion.local"

    # Auto-Schema Discovery
    discovery_sample_pages: int = 5
    discovery_max_context_ratio: float = 0.80
    discovery_cache_enabled: bool = True

    # OCR Processing
    ocr_concurrency: int = 8

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


def get_settings() -> Settings:
    """Factory function for dependency injection."""
    return Settings()
