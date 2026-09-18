"""
Redis client factory (WBS 9.6: Redis backs the job queue and sessions).

Two backends selected by settings.redis_backend:

- "fake" (default): fakeredis, an in-process pure-Python implementation of the
  Redis protocol. No server, no Docker -- this is what runs today in a plain
  venv. State lives only for this process's lifetime and is not shared across
  workers; fine for one dev process, not for anything concurrent or durable.
- "real": an actual Redis server via redis-py. Set REDIS_BACKEND=real once one
  exists; redis_url governs where to find it.

app/services/queue.py and app/services/sessions.py don't care which client
they're holding -- fakeredis is deliberately a drop-in for the same API.
"""

import fakeredis
import redis

from app.core.config import settings

_client = None


def get_redis_client():
    global _client
    if _client is None:
        if settings.redis_backend == "fake":
            _client = fakeredis.FakeRedis(decode_responses=True)
        else:
            _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client
