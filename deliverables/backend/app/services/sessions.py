"""
Session store on Redis (WBS 9.6). Holds nothing but opaque session data keyed by
session id with a TTL -- authentication itself is WBS 9.4 (SSO and provisioning),
not yet built; this is the storage primitive that layer will write into once a
person can actually log in.
"""

import json
from dataclasses import dataclass
from typing import Any

import redis

DEFAULT_TTL_SECONDS = 8 * 60 * 60  # one working day


@dataclass
class SessionStore:
    client: redis.Redis
    prefix: str = "session:"

    def _key(self, session_id: str) -> str:
        return f"{self.prefix}{session_id}"

    def create(self, session_id: str, data: dict[str, Any], ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.client.setex(self._key(session_id), ttl_seconds, json.dumps(data))

    def get(self, session_id: str) -> dict[str, Any] | None:
        raw = self.client.get(self._key(session_id))
        return json.loads(raw) if raw is not None else None

    def delete(self, session_id: str) -> None:
        self.client.delete(self._key(session_id))
