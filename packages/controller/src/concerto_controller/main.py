from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from concerto_controller.api.agents import router as agents_router
from concerto_controller.api.jobs import router as jobs_router
from concerto_controller.api.ws import router as ws_router
from concerto_controller.config import settings
from concerto_controller.db.session import init_db
from concerto_controller.scheduler.heartbeat import heartbeat_monitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database ready")

    # Start heartbeat monitor
    hb_task = asyncio.create_task(heartbeat_monitor())
    logger.info("Controller started on %s:%s", settings.ws_host, settings.ws_port)

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
app.include_router(jobs_router)
app.include_router(agents_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


def run() -> None:
    uvicorn.run(
        "concerto_controller.main:app",
        host=settings.ws_host,
        port=settings.ws_port,
        log_level="info",
    )


if __name__ == "__main__":
    run()
