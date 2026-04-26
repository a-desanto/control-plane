import math
import time

import redis.asyncio as aioredis


async def check_rate_limit(
    client: aioredis.Redis,
    app_id: str,
    limit_per_minute: int,
) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds).

    Uses a fixed-window counter keyed by (app_id, minute_bucket).
    retry_after_seconds is 0 when allowed.
    """
    now = time.time()
    bucket = int(now // 60)
    key = f"rl:{app_id}:{bucket}"

    count = await client.incr(key)
    if count == 1:
        # First request in this window — set TTL to 120s so stale keys expire.
        await client.expire(key, 120)

    if count > limit_per_minute:
        seconds_until_next_window = 60 - int(now % 60)
        return False, seconds_until_next_window

    return True, 0
