import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.routes.health import router as health_router
from app.routes.intent import router as intent_router

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(application: FastAPI):
    log.info("api_gateway_starting", paperclipai_url=os.environ.get("PAPERCLIPAI_INTERNAL_URL"))
    yield
    log.info("api_gateway_stopped")


app = FastAPI(title="api-gateway", version="v0.1.0", lifespan=lifespan)

app.include_router(health_router)
app.include_router(intent_router)
