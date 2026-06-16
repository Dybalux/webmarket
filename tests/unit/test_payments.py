"""Unit tests for webhook signature validation in services/payments.py.

Covers all branches of _validate_signature:
  4.1 — valid HMAC → no exception raised
  4.2 — invalid HMAC → ForbiddenError raised
  4.3 — missing signature in production → ForbiddenError
  4.3b — missing secret in production → ForbiddenError
  4.3c — unsigned allowed in dev when env var is true
  4.3d — unsigned rejected in dev when env var is false
  4.5 — regression: authenticate_user not in security module
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from services.exceptions import ForbiddenError
from services.payments import _validate_signature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = "unit-test-webhook-secret"


def _make_valid_signature(
    payment_id: str, x_request_id: str, secret: str = _SECRET,
) -> str:
    """Build a valid x-signature header for the given params."""
    ts = "1234567890"
    msg = f"id:{payment_id};request-id:{x_request_id};ts:{ts};"
    expected = hmac.new(
        secret.encode(), msg.encode(), hashlib.sha256
    ).hexdigest()
    return f"ts={ts},v1={expected}"


# ---------------------------------------------------------------------------
# 4.1 — Valid HMAC → no exception
# ---------------------------------------------------------------------------

def test_validate_signature_valid_hmac(monkeypatch):
    """Valid HMAC signature should not raise an exception."""
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_WEBHOOK_SECRET", _SECRET,
    )
    monkeypatch.setattr("services.payments.settings.ENV", "development")

    sig = _make_valid_signature("pay_123", "req_456")

    # Should not raise
    _validate_signature("pay_123", sig, "req_456")


# ---------------------------------------------------------------------------
# 4.2 — Invalid HMAC → ForbiddenError
# ---------------------------------------------------------------------------

def test_validate_signature_invalid_hmac(monkeypatch):
    """HMAC mismatch should raise ForbiddenError."""
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_WEBHOOK_SECRET", _SECRET,
    )
    monkeypatch.setattr("services.payments.settings.ENV", "development")

    # A valid-looking signature computed with a DIFFERENT secret
    sig = _make_valid_signature("pay_123", "req_456", secret="wrong-secret")

    with pytest.raises(ForbiddenError, match="Invalid webhook signature"):
        _validate_signature("pay_123", sig, "req_456")


def test_validate_signature_malformed_header(monkeypatch):
    """Malformed x-signature (missing ts/v1) should raise ForbiddenError."""
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_WEBHOOK_SECRET", _SECRET,
    )
    monkeypatch.setattr("services.payments.settings.ENV", "development")

    with pytest.raises(ForbiddenError, match="Invalid webhook signature"):
        _validate_signature("pay_123", "garbage-header", "req_456")


# ---------------------------------------------------------------------------
# 4.3 — Missing signature scenarios
# ---------------------------------------------------------------------------

def test_validate_signature_missing_in_production(monkeypatch):
    """Missing x-signature in production should raise ForbiddenError."""
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_WEBHOOK_SECRET", _SECRET,
    )
    monkeypatch.setattr("services.payments.settings.ENV", "production")
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS",
        False,
    )

    with pytest.raises(ForbiddenError, match="Missing webhook signature"):
        _validate_signature("pay_123", None, "req_456")


def test_validate_signature_missing_secret_in_production(monkeypatch):
    """Missing MERCADOPAGO_WEBHOOK_SECRET in production → ForbiddenError."""
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_WEBHOOK_SECRET", None,
    )
    monkeypatch.setattr("services.payments.settings.ENV", "production")

    with pytest.raises(ForbiddenError, match="not configured"):
        _validate_signature("pay_123", "any-sig", "req_456")


def test_validate_signature_unsigned_allowed_in_dev(monkeypatch):
    """Unsigned webhooks allowed in dev when env var is true."""
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_WEBHOOK_SECRET", _SECRET,
    )
    monkeypatch.setattr("services.payments.settings.ENV", "development")
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS",
        True,
    )

    # Should not raise
    _validate_signature("pay_123", None, "req_456")


def test_validate_signature_unsigned_rejected_in_dev_when_disabled(monkeypatch):
    """Unsigned webhooks rejected in dev when env var is false (default)."""
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_WEBHOOK_SECRET", _SECRET,
    )
    monkeypatch.setattr("services.payments.settings.ENV", "development")
    monkeypatch.setattr(
        "services.payments.settings.MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS",
        False,
    )

    with pytest.raises(ForbiddenError, match="Missing webhook signature"):
        _validate_signature("pay_123", None, "req_456")


# ---------------------------------------------------------------------------
# 4.5 — Regression: authenticate_user deleted
# ---------------------------------------------------------------------------

def test_authenticate_user_not_in_security_module():
    """Regression: authenticate_user must not exist in security.py."""
    import security

    assert not hasattr(security, "authenticate_user"), (
        "authenticate_user backdoor must be removed from security.py"
    )
