"""Integration tests for webhook security — end-to-end 403 on invalid signature.

Mounts the payments router on the test app and confirms ForbiddenError
from _validate_signature propagates past the catch-all in process_webhook
to produce a 403 RFC 9457 response.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi import FastAPI


_SECRET = "integration-test-webhook-secret"


def _make_valid_signature(payment_id: str, x_request_id: str = "") -> str:
    """Build a valid x-signature header."""
    ts = "9876543210"
    msg = f"id:{payment_id};request-id:{x_request_id};ts:{ts};"
    expected = hmac.new(
        _SECRET.encode(), msg.encode(), hashlib.sha256
    ).hexdigest()
    return f"ts={ts},v1={expected}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mount_payments_router(test_app: FastAPI) -> None:
    """Mount the payments router on the test app (idempotent)."""
    from routers.payments import router as payments_router

    # Avoid double-mounting if another test already included it.
    registered = {r.path for r in test_app.routes}
    if "/webhook" in registered:
        return
    test_app.include_router(payments_router)


def _configure_webhook_settings(monkeypatch, *, allow_unsigned: bool = False) -> None:
    """Set MERCADOPAGO_WEBHOOK_SECRET and related settings."""
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_WEBHOOK_SECRET", _SECRET,
    )
    monkeypatch.setattr("services.payments.settings.ENV", "development")
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS",
        allow_unsigned,
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_bad_signature_returns_403(test_app, test_client, monkeypatch):
    """POST /webhook with bad x-signature → 403 RFC 9457.

    This confirms ForbiddenError from _validate_signature propagates
    through process_webhook (past the catch-all) to the global handler.
    """
    _mount_payments_router(test_app)
    _configure_webhook_settings(monkeypatch)

    response = await test_client.post(
        "/webhook?topic=payment&id=123456",
        headers={"x-signature": "ts=bad,v1=invalid"},
    )

    assert response.status_code == 403
    assert response.headers["Content-Type"] == "application/problem+json"
    body = response.json()
    assert body["title"] == "Forbidden"
    assert body["status"] == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_missing_signature_in_production_403(
    test_app, test_client, monkeypatch,
):
    """POST /webhook without x-signature when ENV=production → 403."""
    _mount_payments_router(test_app)
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_WEBHOOK_SECRET", _SECRET,
    )
    monkeypatch.setattr("services.payments.settings.ENV", "production")
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS",
        False,
    )

    response = await test_client.post(
        "/webhook?topic=payment&id=123456",
        # No x-signature header
    )

    assert response.status_code == 403
    body = response.json()
    assert body["status"] == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_valid_signature_no_exception(
    test_app, test_client, monkeypatch,
):
    """POST /webhook with valid signature → 200 (signature passes).

    The response will be 200 because the webhook with topic=payment
    and id=123456 won't match a real payment — but the signature
    check succeeds, proving it's not blocking valid webhooks.
    """
    _mount_payments_router(test_app)
    _configure_webhook_settings(monkeypatch)

    sig = _make_valid_signature("123456")
    response = await test_client.post(
        "/webhook?topic=payment&id=123456",
        headers={"x-signature": sig},
    )

    # 200 because signature passes; any downstream error (e.g. MP SDK
    # not configured in test CI) is NOT a 403 — signature check is OK.
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_valid_signature_with_x_request_id(
    test_app, test_client, monkeypatch,
):
    """Valid signature with x-request-id header → 200."""
    _mount_payments_router(test_app)
    _configure_webhook_settings(monkeypatch)

    sig = _make_valid_signature("123456", "req-int-2")
    response = await test_client.post(
        "/webhook?topic=payment&id=123456",
        headers={
            "x-signature": sig,
            "x-request-id": "req-int-2",
        },
    )

    assert response.status_code == 200
