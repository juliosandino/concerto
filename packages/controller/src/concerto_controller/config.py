"""Controller configuration via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Controller runtime settings from environment variables."""

    database_url: str = "postgresql+asyncpg://concerto:concerto@localhost:5432/concerto"
    heartbeat_timeout_sec: int = 15
    heartbeat_check_interval_sec: int = 5
    ws_host: str = "0.0.0.0"
    ws_port: int = 8000

    model_config = {"env_prefix": "CONCERTO_"}


settings = Settings()
