from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AQH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Agent Quality Harness"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+psycopg://agent_quality:agent_quality@localhost:5432/agent_quality"
    )
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_key: str = "aqh:eval-runs"
    redis_claim_timeout_seconds: int = Field(default=5, ge=1, le=60)
    worker_lease_seconds: int = Field(default=60, ge=10, le=3600)
    worker_heartbeat_seconds: int = Field(default=10, ge=1, le=300)
    inspect_max_samples: int = Field(default=8, ge=1, le=128)
    inspect_log_dir: Path = Path(".tmp/inspect-logs")
    otel_enabled: bool = False
    otel_service_name: str = "agent-quality-harness-api"
    otel_worker_service_name: str = "agent-quality-harness-worker"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    jaeger_base_url: str = "http://localhost:16686"
    opa_enabled: bool = False
    opa_url: str = "http://localhost:8181"
    opa_timeout_seconds: float = Field(default=2.0, ge=0.1, le=10.0)
    demo_agent_endpoint: str = "http://127.0.0.1:8020/invoke"
    demo_dataset_path: Path = Path("datasets/demo-fixture-core-v1.json")
    jwt_secret: str = "development-only-change-me-please-use-a-random-64-character-secret"
    access_token_minutes: int = Field(default=15, ge=1, le=120)
    refresh_session_days: int = Field(default=7, ge=1, le=30)
    refresh_cookie_name: str = "aqh_refresh"
    refresh_cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
