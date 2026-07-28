"""Unit tests for utils/idempotency.py.

Covers:
  - UUID-4 validation (valid, invalid, None, empty)
  - fallback_key derivation (Pydantic model + string)
  - get_or_set two-phase flow (NX miss → execute → cache; NX hit → replay)
  - IN_FLIGHT → 409
  - Fail-open on RedisError
  - Cross-user key isolation
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from tests.conftest import FakeRedis
from utils.idempotency import (
    _IN_FLIGHT,
    build_key,
    fallback_key,
    get_or_set,
    validate_key,
)


# ---------------------------------------------------------------------------
# Dummy payload for fallback_key tests
# ---------------------------------------------------------------------------


class _Payload(BaseModel):
    name: str
    quantity: int


# ---------------------------------------------------------------------------
# validate_key
# ---------------------------------------------------------------------------


class TestValidateKey:
    def test_valid_uuid4_returns_lowercase(self):
        raw = "A1B2C3D4-E5F6-4A7B-8C9D-0E1F2A3B4C5D"
        result = validate_key(raw)
        assert result == raw.lower()

    def test_none_returns_none(self):
        assert validate_key(None) is None

    def test_empty_string_returns_none(self):
        assert validate_key("") is None
        assert validate_key("   ") is None

    def test_invalid_uuid_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_key("not-a-uuid")
        assert exc_info.value.status_code == 400

    def test_uuid_v1_rejected(self):
        # v1 has version nibble = 1, not 4
        v1 = str(uuid.uuid1())
        with pytest.raises(HTTPException) as exc_info:
            validate_key(v1)
        assert exc_info.value.status_code == 400

    def test_uuid_v4_accepted(self):
        v4 = str(uuid.uuid4())
        assert validate_key(v4) == v4


# ---------------------------------------------------------------------------
# fallback_key
# ---------------------------------------------------------------------------


class TestFallbackKey:
    def test_deterministic_with_model(self):
        p = _Payload(name="test", quantity=2)
        k1 = fallback_key("user1", "orders", p)
        k2 = fallback_key("user1", "orders", p)
        assert k1 == k2
        assert k1.startswith("fb:")

    def test_different_users_different_keys(self):
        p = _Payload(name="test", quantity=2)
        k1 = fallback_key("user1", "orders", p)
        k2 = fallback_key("user2", "orders", p)
        assert k1 != k2

    def test_different_payloads_different_keys(self):
        k1 = fallback_key("u", "orders", _Payload(name="a", quantity=1))
        k2 = fallback_key("u", "orders", _Payload(name="b", quantity=2))
        assert k1 != k2

    def test_string_payload(self):
        k1 = fallback_key("u", "payments", "order123")
        k2 = fallback_key("u", "payments", "order456")
        assert k1 != k2
        assert k1.startswith("fb:")


# ---------------------------------------------------------------------------
# build_key
# ---------------------------------------------------------------------------


class TestBuildKey:
    def test_with_uuid(self):
        key = build_key("u1", "orders", "abc-123")
        assert key == "idem:u1:orders:abc-123"

    def test_with_fallback(self):
        key = build_key("u1", "orders", "fb:hash123")
        assert key == "idem:u1:orders:fb:hash123"


# ---------------------------------------------------------------------------
# get_or_set — happy path
# ---------------------------------------------------------------------------


class TestGetOrSet:
    @pytest.mark.asyncio
    async def test_first_call_executes_and_caches(self):
        redis = FakeRedis()
        called = False

        async def producer():
            nonlocal called
            called = True
            return {"id": "order-1"}

        result, was_cached = await get_or_set(
            redis, "idem:u1:orders:uuid1", producer
        )
        assert result == {"id": "order-1"}
        assert was_cached is False
        assert called is True
        # Should be cached now
        assert "idem:u1:orders:uuid1" in redis._store

    @pytest.mark.asyncio
    async def test_replay_returns_cached(self):
        redis = FakeRedis()
        call_count = 0

        async def producer():
            nonlocal call_count
            call_count += 1
            return {"id": "order-1"}

        # First call — execute
        await get_or_set(redis, "idem:u1:orders:uuid1", producer)
        # Second call — replay
        result, was_cached = await get_or_set(
            redis, "idem:u1:orders:uuid1", producer
        )
        assert result == {"id": "order-1"}
        assert was_cached is True
        assert call_count == 1  # producer called only once

    @pytest.mark.asyncio
    async def test_in_flight_returns_409(self):
        redis = FakeRedis()
        # Simulate IN_FLIGHT state
        await redis.set("idem:u1:orders:uuid1", _IN_FLIGHT, nx=True, ex=86400)

        async def producer():
            return {"id": "should-not-run"}

        with pytest.raises(HTTPException) as exc_info:
            await get_or_set(redis, "idem:u1:orders:uuid1", producer)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_fail_open_on_redis_error(self):
        """When Redis is down, producer runs without idempotency."""

        class BrokenRedis:
            async def set(self, *a, **kw):
                from redis.exceptions import ConnectionError
                raise ConnectionError("Redis down")

            async def get(self, *a, **kw):
                from redis.exceptions import ConnectionError
                raise ConnectionError("Redis down")

        called = False

        async def producer():
            nonlocal called
            called = True
            return {"id": "order-1"}

        result, was_cached = await get_or_set(
            BrokenRedis(), "idem:u1:orders:uuid1", producer
        )
        assert result == {"id": "order-1"}
        assert was_cached is False
        assert called is True

    @pytest.mark.asyncio
    async def test_cross_user_isolation(self):
        """Same UUID sent by different users produces independent results."""
        redis = FakeRedis()
        uid = str(uuid.uuid4())

        async def producer_a():
            return {"user": "A", "order": "1"}

        async def producer_b():
            return {"user": "B", "order": "2"}

        result_a, _ = await get_or_set(redis, f"idem:userA:orders:{uid}", producer_a)
        result_b, _ = await get_or_set(redis, f"idem:userB:orders:{uid}", producer_b)

        assert result_a["user"] == "A"
        assert result_b["user"] == "B"

    @pytest.mark.asyncio
    async def test_ttl_is_set(self):
        redis = FakeRedis()

        async def producer():
            return {"ok": True}

        await get_or_set(redis, "idem:u1:orders:uuid1", producer, ttl=3600)
        assert redis._ttls.get("idem:u1:orders:uuid1") == 3600

    @pytest.mark.asyncio
    async def test_cached_response_replay_json(self):
        """Cached response is valid JSON and matches original."""
        redis = FakeRedis()

        async def producer():
            return {"total": 100.50, "items": [{"name": "Beer"}]}

        result, _ = await get_or_set(redis, "idem:u1:orders:uuid1", producer)
        replayed, was_cached = await get_or_set(
            redis, "idem:u1:orders:uuid1", producer
        )
        assert replayed == result
        assert was_cached is True
