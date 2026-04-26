import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import events as ev
from app.api.intent import router as intent_router
from app.middleware.claims import ClaimsVerificationMiddleware
from app.tool_registry import load_tool_registry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    load_tool_registry()
    try:
        await ev.start_listener()
    except Exception:
        logger.exception("Failed to start Postgres event listener; SSE fan-out disabled")
    yield
    await ev.stop_listener()


app = FastAPI(title="paperclipai", version="v0.1.0", lifespan=lifespan)

app.add_middleware(ClaimsVerificationMiddleware)
app.include_router(intent_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
