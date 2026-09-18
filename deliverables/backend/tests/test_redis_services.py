"""
Regression tests for the Redis-backed queue and session store (WBS 9.6), against
fakeredis instead of a live Redis instance.
"""

import fakeredis
import pytest

from app.services.queue import RedisQueue
from app.services.sessions import SessionStore


@pytest.fixture()
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


def test_queue_enqueue_dequeue_is_fifo(redis_client):
    queue = RedisQueue(client=redis_client, name="jobs:test")

    queue.enqueue({"job": "recompute", "opportunity_id": "1"})
    queue.enqueue({"job": "recompute", "opportunity_id": "2"})
    assert len(queue) == 2

    first = queue.dequeue()
    second = queue.dequeue()
    assert first == {"job": "recompute", "opportunity_id": "1"}
    assert second == {"job": "recompute", "opportunity_id": "2"}
    assert queue.dequeue() is None
    assert len(queue) == 0


def test_queue_isolated_by_name(redis_client):
    a = RedisQueue(client=redis_client, name="jobs:a")
    b = RedisQueue(client=redis_client, name="jobs:b")

    a.enqueue({"x": 1})
    assert len(a) == 1
    assert len(b) == 0
    assert b.dequeue() is None


def test_session_create_get_delete(redis_client):
    store = SessionStore(client=redis_client)

    store.create("sess-1", {"owner": "jdoe", "region": "Korea"})
    assert store.get("sess-1") == {"owner": "jdoe", "region": "Korea"}

    store.delete("sess-1")
    assert store.get("sess-1") is None


def test_session_missing_returns_none(redis_client):
    store = SessionStore(client=redis_client)
    assert store.get("does-not-exist") is None


def test_session_expires_after_ttl(redis_client):
    store = SessionStore(client=redis_client)
    store.create("sess-short", {"owner": "jdoe"}, ttl_seconds=1)
    assert store.get("sess-short") == {"owner": "jdoe"}

    redis_client.pexpire(store._key("sess-short"), -1)  # force-expire instead of sleeping in a test
    assert store.get("sess-short") is None
