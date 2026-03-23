from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from concerto_controller.config import settings
from concerto_controller.db.models import Base

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables. Called once at startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency that yields a DB session."""
    async with async_session() as session:
        yield session
