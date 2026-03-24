"""Controller FastAPI application and startup lifecycle."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from concerto_controller.api.agents import router as agents_router
from concerto_controller.api.dashboard_ws import router as dashboard_ws_router
from concerto_controller.api.jobs import router as jobs_router
from concerto_controller.api.ws import router as ws_router
from concerto_controller.config import settings
from concerto_controller.db.session import init_db
from concerto_controller.scheduler.heartbeat import heartbeat_monitor
from fastapi import FastAPI
from loguru import logger


class _InterceptHandler(logging.Handler):
    """Route standard-library log records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Manage controller startup and shutdown lifecycle."""
    # Startup
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database ready")

    # Start heartbeat monitor
    hb_task = asyncio.create_task(heartbeat_monitor())
    logger.info(f"Controller started on {settings.ws_host}:{settings.ws_port}")

    yield

    # Shutdown
    hb_task.cancel()
    try:
        await hb_task
    except asyncio.CancelledError:
        pass
    logger.info("Controller shut down")


app = FastAPI(title="Concerto TSS Controller", version="0.1.0", lifespan=lifespan)
app.include_router(ws_router)
app.include_router(dashboard_ws_router)
app.include_router(jobs_router)
app.include_router(agents_router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


def run() -> None:
    """Start the controller server."""
    uvicorn.run(
        "concerto_controller.main:app",
        host=settings.ws_host,
        port=settings.ws_port,
        log_level="info",
    )


if __name__ == "__main__":
    run()
