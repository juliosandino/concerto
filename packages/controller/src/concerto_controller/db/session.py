from pathlib import Path

from alembic import command
from alembic.config import Config
from concerto_controller.config import settings
from concerto_controller.db.models import (  # noqa: F401 – keep for Alembic target_metadata
    Base,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


def _alembic_cfg() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


async def init_db() -> None:
    """Run Alembic migrations to bring the database up to date."""
    import asyncio

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, command.upgrade, _alembic_cfg(), "head")


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency that yields a DB session."""
    async with async_session() as session:
        yield session
