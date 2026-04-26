from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uuid
import logging

from app.tool_registry import load_tool_registry

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(application: FastAPI):
    load_tool_registry()
    yield


app = FastAPI(title="paperclipai", version="v0", lifespan=lifespan)


@app.post("/intent")
async def create_intent(request: Request):
    payload = await request.json()
    intent_id = payload.get("intent_id") or str(uuid.uuid4())

    logging.info(f"Received intent {intent_id}: {payload}")

    return JSONResponse(
        status_code=202,
        content={
            "intent_id": intent_id,
            "status": "accepted",
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
