"""Cross-process SSE fan-out via Postgres LISTEN/NOTIFY.

The worker NOTIFYs 'paperclipai_events' with a JSON payload; this module
holds a single asyncpg LISTEN connection and fans notifications out to
per-intent asyncio Queues consumed by SSE handlers.
"""

import asyncio
import json
import logging
import os
from collections import defaultdict

import asyncpg

logger = logging.getLogger(__name__)

CHANNEL = "paperclipai_events"

_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
_pg_conn: asyncpg.Connection | None = None


def _on_notification(connection, pid, channel, payload: str) -> None:
    try:
        data = json.loads(payload)
        intent_id = data.get("intent_id")
        if not intent_id:
            return
        for q in list(_queues.get(intent_id, [])):
            q.put_nowait(data)
    except Exception:
        logger.exception("Error dispatching notification payload=%r", payload)


async def start_listener(database_url: str | None = None) -> None:
    global _pg_conn
    url = database_url or os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/paperclipai",
    )
    raw_url = url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    _pg_conn = await asyncpg.connect(raw_url)
    await _pg_conn.add_listener(CHANNEL, _on_notification)
    logger.info("Listening on Postgres channel '%s'", CHANNEL)


async def stop_listener() -> None:
    global _pg_conn
    if _pg_conn is not None:
        try:
            await _pg_conn.remove_listener(CHANNEL, _on_notification)
            await _pg_conn.close()
        except Exception:
            logger.exception("Error closing events listener")
        finally:
            _pg_conn = None


def subscribe(intent_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _queues[intent_id].append(q)
    return q


def unsubscribe(intent_id: str, q: asyncio.Queue) -> None:
    bucket = _queues.get(intent_id)
    if bucket is None:
        return
    try:
        bucket.remove(q)
    except ValueError:
        pass
    if not bucket:
        _queues.pop(intent_id, None)
