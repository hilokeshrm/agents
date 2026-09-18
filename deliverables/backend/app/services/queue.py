"""
Job queue on Redis (WBS 9.6). A thin wrapper over a Redis list, not a task
framework -- the architecture doc leaves the actual worker as "cron or Temporal"
(docs/02-architecture/OppTrack_Complete_Architecture.html, section 11); this is
the primitive whichever of those ends up driving jobs through.

The client is injected rather than pulled from app.core.redis_client at import
time, so tests can pass a fake client and callers can share one connection.
"""

import json
from dataclasses import dataclass
from typing import Any

import redis


@dataclass
class RedisQueue:
    client: redis.Redis
    name: str

    def enqueue(self, payload: dict[str, Any]) -> None:
        self.client.rpush(self.name, json.dumps(payload))

    def dequeue(self) -> dict[str, Any] | None:
        """Non-blocking pop. A worker polls or wraps this in its own blocking
        loop; kept non-blocking here so it behaves the same against a real
        Redis server and against fakeredis in tests."""
        raw = self.client.lpop(self.name)
        return json.loads(raw) if raw is not None else None

    def __len__(self) -> int:
        return self.client.llen(self.name)
