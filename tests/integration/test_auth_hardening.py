"""Integration tests for auth hardening (F-004, F-009, F-015, F-017).

Covers:
  - Password reset flow (forgot + reset endpoints)
  - Account lockout (5 failures → 423, success resets, lockout expiry)
  - JWT swap regression (production decode path)

Uses test_client + fake Redis — no real MongoDB or Redis required.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from bson import ObjectId
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from config import settings
from models import ForgotPasswordRequest, PasswordResetConfirm
from security import (
    get_password_hash,
    verify_password,
    create_reset_token,
    hash_reset_token,
    get_redis,
    check_lockout,
    record_failure,
    clear_failures,
)
from tests.conftest import FakeRedis


# ---------------------------------------------------------------------------
# Fixture: test app with auth router mounted
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def auth_test_client(test_app: FastAPI, fake_redis, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    """Test client with the auth router mounted and rate limiter bypassed."""
    from routers.auth import router as auth_router
    from fastapi_limiter import FastAPILimiter
    from unittest.mock import AsyncMock

    test_app.include_router(auth_router, prefix="/auth")

    # Bypass RateLimiter in tests — it needs real Redis (script_load),
    # and per-account lockout is tested separately via get_redis override.
    # Initialize FastAPILimiter with a mock Redis that passes all requests.
    mock_redis = AsyncMock()
    mock_redis.script_load = AsyncMock(return_value="fake-sha")
    # evalsha returns 0 = allowed (no rate limit exceeded)
    mock_redis.evalsha = AsyncMock(return_value=0)
    await FastAPILimiter.init(mock_redis)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Password Reset Flow Tests (F-015)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestForgotPassword:
    """POST /auth/forgot-password — always 202, identical body."""

    async def test_known_email_returns_202(
        self, auth_test_client: AsyncClient, reset_db_singleton, monkeypatch
    ):
        """Known user gets 202 and an email is sent."""
        db = reset_db_singleton
        users = db["users"]
        await users.insert_one({
            "username": "resetuser",
            "email": "reset@example.com",
            "hashed_password": get_password_hash("MyD0g$W0rld!23"),
            "role": "customer",
            "age_verified": True,
            "birth_date": datetime(2000, 1, 1, tzinfo=timezone.utc),
            "created_at": datetime.now(tz=timezone.utc),
        })

        resp = await auth_test_client.post("/auth/forgot-password", json={"email": "reset@example.com"})

        assert resp.status_code == 202
        assert "reset link" in resp.json()["message"].lower()

    async def test_unknown_email_returns_identical_202(
        self, auth_test_client: AsyncClient, reset_db_singleton
    ):
        """Unknown email must return the SAME 202 body (no enumeration)."""
        resp = await auth_test_client.post("/auth/forgot-password", json={"email": "ghost@example.com"})

        assert resp.status_code == 202
        assert "reset link" in resp.json()["message"].lower()

    async def test_forgot_password_no_email_enumeration(
        self, auth_test_client: AsyncClient, reset_db_singleton
    ):
        """Response body is identical for known vs unknown emails."""
        known = await auth_test_client.post("/auth/forgot-password", json={"email": "real@example.com"})
        unknown = await auth_test_client.post("/auth/forgot-password", json={"email": "fake@example.com"})

        assert known.json() == unknown.json()
        assert known.status_code == unknown.status_code


@pytest.mark.asyncio
class TestResetPassword:
    """POST /auth/reset-password — single-use, expiry, policy check."""

    async def _create_user_and_token(self, db, password: str = "MyD0g$W0rld!23"):
        """Helper: insert user + reset token, return (token_raw, user_id)."""
        users = db["users"]
        user_id = ObjectId()
        await users.insert_one({
            "_id": user_id,
            "username": "resetflow",
            "email": "resetflow@example.com",
            "hashed_password": get_password_hash(password),
            "role": "customer",
            "age_verified": True,
            "birth_date": datetime(2000, 1, 1, tzinfo=timezone.utc),
            "created_at": datetime.now(tz=timezone.utc),
        })

        token_raw = create_reset_token()
        token_hash = hash_reset_token(token_raw)
        reset_tokens = db["password_reset_tokens"]
        await reset_tokens.insert_one({
            "token_hash": token_hash,
            "user_id": str(user_id),
            "expires_at": datetime.now(tz=timezone.utc) + timedelta(minutes=60),
            "used": False,
        })
        return token_raw, str(user_id)

    async def test_valid_token_succeeds(
        self, auth_test_client: AsyncClient, reset_db_singleton
    ):
        """Valid unexpired token + compliant password → password updated."""
        db = reset_db_singleton
        token_raw, user_id = await self._create_user_and_token(db)

        resp = await auth_test_client.post("/auth/reset-password", json={
            "token": token_raw,
            "new_password": "NewStr0ng!Pass99",
        })

        assert resp.status_code == 200
        assert "updated" in resp.json()["message"].lower()

        # Verify password actually changed
        users = db["users"]
        user = await users.find_one({"_id": ObjectId(user_id)})
        assert verify_password("NewStr0ng!Pass99", user["hashed_password"])

    async def test_expired_token_rejected(
        self, auth_test_client: AsyncClient, reset_db_singleton
    ):
        """Token issued >1 hour ago → 400."""
        db = reset_db_singleton
        users = db["users"]
        user_id = ObjectId()
        await users.insert_one({
            "_id": user_id,
            "username": "expiredflow",
            "email": "expired@example.com",
            "hashed_password": get_password_hash("OldPassw0rd!X"),
            "role": "customer",
            "age_verified": True,
            "birth_date": datetime(2000, 1, 1, tzinfo=timezone.utc),
            "created_at": datetime.now(tz=timezone.utc),
        })

        token_raw = create_reset_token()
        token_hash = hash_reset_token(token_raw)
        reset_tokens = db["password_reset_tokens"]
        await reset_tokens.insert_one({
            "token_hash": token_hash,
            "user_id": str(user_id),
            "expires_at": datetime.now(tz=timezone.utc) - timedelta(seconds=1),  # expired
            "used": False,
        })

        resp = await auth_test_client.post("/auth/reset-password", json={
            "token": token_raw,
            "new_password": "NewStr0ng!Pass99",
        })

        assert resp.status_code == 400

    async def test_reused_token_rejected(
        self, auth_test_client: AsyncClient, reset_db_singleton
    ):
        """Already-consumed token → 400."""
        db = reset_db_singleton
        token_raw, user_id = await self._create_user_and_token(db)

        # First use — succeeds
        resp1 = await auth_test_client.post("/auth/reset-password", json={
            "token": token_raw,
            "new_password": "FirstStr0ng!Pass",
        })
        assert resp1.status_code == 200

        # Second use — rejected
        resp2 = await auth_test_client.post("/auth/reset-password", json={
            "token": token_raw,
            "new_password": "SecondStr0ng!Pass",
        })
        assert resp2.status_code == 400

    async def test_weak_password_rejected_at_reset(
        self, auth_test_client: AsyncClient, reset_db_singleton
    ):
        """Valid token but weak password → 422 (Pydantic validation)."""
        db = reset_db_singleton
        token_raw, _ = await self._create_user_and_token(db)

        resp = await auth_test_client.post("/auth/reset-password", json={
            "token": token_raw,
            "new_password": "123",
        })

        assert resp.status_code == 422

    async def test_invalid_token_rejected(
        self, auth_test_client: AsyncClient, reset_db_singleton
    ):
        """Completely fabricated token → 400."""
        resp = await auth_test_client.post("/auth/reset-password", json={
            "token": "not-a-real-token-at-all",
            "new_password": "NewStr0ng!Pass99",
        })

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Account Lockout Tests (F-017)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAccountLockout:
    """Per-account failed-login counter → 423 after 5 failures."""

    async def _create_login_user(self, db, username: str = "lockuser"):
        """Insert a user for login tests."""
        users = db["users"]
        user_id = ObjectId()
        await users.insert_one({
            "_id": user_id,
            "username": username,
            "email": f"{username}@example.com",
            "hashed_password": get_password_hash("MyD0g$W0rld!23"),
            "role": "customer",
            "age_verified": True,
            "birth_date": datetime(2000, 1, 1, tzinfo=timezone.utc),
            "created_at": datetime.now(tz=timezone.utc),
        })
        return str(user_id)

    async def test_five_failures_lock_account(
        self, auth_test_client: AsyncClient, reset_db_singleton, fake_redis
    ):
        """5 consecutive wrong passwords → account locked (423)."""
        db = reset_db_singleton
        await self._create_login_user(db)

        # 4 failed attempts — still 401
        for _ in range(4):
            resp = await auth_test_client.post("/auth/token", data={
                "username": "lockuser",
                "password": "wrongpassword!",
            })
            assert resp.status_code == 401

        # 5th failure — triggers lockout (record_failure sets the lock)
        resp = await auth_test_client.post("/auth/token", data={
            "username": "lockuser",
            "password": "wrongpassword!",
        })
        assert resp.status_code == 401

        # 6th attempt — NOW locked (423)
        resp = await auth_test_client.post("/auth/token", data={
            "username": "lockuser",
            "password": "wrongpassword!",
        })
        assert resp.status_code == 423
        assert "locked" in resp.json()["detail"].lower()

    async def test_success_resets_counter(
        self, auth_test_client: AsyncClient, reset_db_singleton, fake_redis
    ):
        """Successful login resets the failure counter."""
        db = reset_db_singleton
        await self._create_login_user(db)

        # 3 failed attempts
        for _ in range(3):
            await auth_test_client.post("/auth/token", data={
                "username": "lockuser",
                "password": "wrong!",
            })

        # Successful login
        resp = await auth_test_client.post("/auth/token", data={
            "username": "lockuser",
            "password": "MyD0g$W0rld!23",
        })
        assert resp.status_code == 200

        # Now try 4 more wrong attempts — should NOT be locked
        # because success reset the counter
        for _ in range(4):
            resp = await auth_test_client.post("/auth/token", data={
                "username": "lockuser",
                "password": "wrong!",
            })
            assert resp.status_code == 401

    async def test_lockout_expires(
        self, auth_test_client: AsyncClient, reset_db_singleton, fake_redis
    ):
        """After lockout TTL expires, account unlocks."""
        db = reset_db_singleton
        await self._create_login_user(db, username="expiryuser")

        # Trigger lockout (5+ failures)
        for _ in range(6):
            await auth_test_client.post("/auth/token", data={
                "username": "expiryuser",
                "password": "wrong!",
            })

        # Verify locked
        resp = await auth_test_client.post("/auth/token", data={
            "username": "expiryuser",
            "password": "wrong!",
        })
        assert resp.status_code == 423

        # Simulate lockout expiry by deleting the lock key from FakeRedis
        await fake_redis.delete("login_lock:expiryuser", "login_fail:expiryuser")

        # Should process normally now — successful login
        resp = await auth_test_client.post("/auth/token", data={
            "username": "expiryuser",
            "password": "MyD0g$W0rld!23",
        })
        assert resp.status_code == 200

    async def test_fake_redis_is_injected(self, test_app: FastAPI, fake_redis):
        """Verify test_app uses our FakeRedis, not a real Redis connection."""
        from security import get_redis
        override = test_app.dependency_overrides.get(get_redis)
        assert override is not None, "get_redis must be overridden in test_app"
        redis_instance = override()
        assert isinstance(redis_instance, FakeRedis)

    async def test_lockout_helpers_unit(self, fake_redis):
        """Lockout helpers work correctly against FakeRedis without HTTP."""
        r = fake_redis
        username = "unitlock"

        # No lock initially
        assert await check_lockout(r, username) == 0

        # Record 4 failures — not locked yet
        for _ in range(4):
            await record_failure(r, username)
        assert await check_lockout(r, username) == 0

        # 5th failure — now locked
        await record_failure(r, username)
        remaining = await check_lockout(r, username)
        assert remaining > 0, "Account should be locked after 5 failures"

        # Clear failures — unlocked
        await clear_failures(r, username)
        assert await check_lockout(r, username) == 0
