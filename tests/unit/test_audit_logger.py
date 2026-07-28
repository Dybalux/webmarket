"""Unit tests for audit_logger module.

Covers:
  - JSON shape: all 6 keys present (S1.1)
  - request=None safe: defaults to "N/A" (S1.3)
  - AuditContext parity: log_audit_ctx output matches log_audit output (S1.2)
  - Log forging prevention: newlines/JSON special chars produce valid single-line JSON (S1.5)
  - _emit never raises
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

import audit_logger
from audit_logger import (
    AuditContext,
    AuditEvent,
    _emit,
    log_audit,
    log_audit_ctx,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_request(
    client_host: str = "1.2.3.4",
    method: str = "POST",
    path: str = "/test",
) -> MagicMock:
    """Build a minimal fake Request for unit tests."""
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = client_host
    req.method = method
    req.url.path = path
    return req


# ---------------------------------------------------------------------------
# Tests — JSON shape (S1.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_json_shape(caplog):
    """_emit produces JSON with all 6 required keys."""
    ctx = AuditContext(client_ip="10.0.0.1", method="GET", path="/x")
    with caplog.at_level(logging.INFO, logger="audit"):
        await _emit(AuditEvent.USER_LOGIN_SUCCESS, ctx, {"user": "a"})

    assert len(caplog.records) >= 1
    record = caplog.records[-1]
    data = json.loads(record.message)

    assert data["event"] == "USER_LOGIN_SUCCESS"
    assert data["client_ip"] == "10.0.0.1"
    assert data["method"] == "GET"
    assert data["path"] == "/x"
    assert "timestamp" in data
    assert data["details"] == {"user": "a"}


# ---------------------------------------------------------------------------
# Tests — request=None safe (S1.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_audit_request_none(caplog):
    """log_audit(event, None, details) defaults to N/A — no exception."""
    with caplog.at_level(logging.INFO, logger="audit"):
        await log_audit(AuditEvent.ORDER_CREATED, None, {"id": "1"})

    data = json.loads(caplog.records[-1].message)
    assert data["client_ip"] == "N/A"
    assert data["method"] == "N/A"
    assert data["path"] == "N/A"


@pytest.mark.asyncio
async def test_log_audit_with_request(caplog):
    """log_audit(event, request, details) extracts request metadata."""
    req = _fake_request("192.168.1.1", "POST", "/auth/token")
    with caplog.at_level(logging.INFO, logger="audit"):
        await log_audit(AuditEvent.USER_LOGIN_SUCCESS, req, {"username": "u"})

    data = json.loads(caplog.records[-1].message)
    assert data["client_ip"] == "192.168.1.1"
    assert data["method"] == "POST"
    assert data["path"] == "/auth/token"


# ---------------------------------------------------------------------------
# Tests — AuditContext parity (S1.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ctx_parity(caplog):
    """log_audit_ctx output structure matches log_audit output exactly."""
    ctx = AuditContext(client_ip="5.5.5.5", method="PUT", path="/orders/1")
    with caplog.at_level(logging.INFO, logger="audit"):
        await log_audit_ctx(AuditEvent.ORDER_CREATED, ctx=ctx, details={"x": 1})

    data = json.loads(caplog.records[-1].message)
    assert set(data.keys()) == {"event", "client_ip", "method", "path", "timestamp", "details"}
    assert data["client_ip"] == "5.5.5.5"
    assert data["method"] == "PUT"
    assert data["path"] == "/orders/1"


# ---------------------------------------------------------------------------
# Tests — Log forging prevention (S1.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_log_forging(caplog):
    """Newlines and JSON special chars produce valid single-line JSON."""
    evil_details = {"msg": "line1\nline2\ttab\"quote"}
    with caplog.at_level(logging.INFO, logger="audit"):
        await log_audit(AuditEvent.USER_LOGIN_FAILED, None, evil_details)

    raw = caplog.records[-1].message
    # Must be a single line (no literal newline in the log record)
    assert "\n" not in raw
    # Must be valid JSON
    data = json.loads(raw)
    assert data["details"]["msg"] == "line1\nline2\ttab\"quote"


# ---------------------------------------------------------------------------
# Tests — _emit never raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_never_raises(caplog):
    """_emit swallows exceptions and logs a warning instead."""
    bad_ctx = AuditContext(client_ip=object(), method="X", path="/")  # type: ignore[arg-type]
    # Should NOT raise
    with caplog.at_level(logging.WARNING):
        await _emit(AuditEvent.ORDER_CREATED, bad_ctx, {})

    # The warning logger should have captured the failure
    assert any("Audit emit failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Tests — AuditEvent enum completeness
# ---------------------------------------------------------------------------


def test_audit_event_count():
    """18 total enum values (6 original + 12 new)."""
    assert len(AuditEvent) == 18


def test_audit_event_new_values_exist():
    """All 12 new event values are present."""
    new_events = [
        "PASSWORD_RESET_REQUESTED",
        "PASSWORD_RESET_COMPLETED",
        "ADMIN_ROLE_CHANGED",
        "ADMIN_USER_DELETED",
        "ADMIN_PRODUCT_CREATED",
        "ADMIN_PRODUCT_UPDATED",
        "PAYMENT_FAILED",
        "MP_PREFERENCE_CREATED",
        "SIGNATURE_INVALID",
        "ORDER_CANCELLED",
        "STOCK_DECREMENTED",
        "STOCK_RESTORED",
    ]
    for name in new_events:
        assert hasattr(AuditEvent, name), f"Missing AuditEvent.{name}"


# ---------------------------------------------------------------------------
# Tests — AuditContext
# ---------------------------------------------------------------------------


def test_audit_context_frozen():
    """AuditContext is frozen (immutable)."""
    ctx = AuditContext(client_ip="1.1.1.1", method="GET", path="/")
    with pytest.raises(AttributeError):
        ctx.client_ip = "2.2.2.2"  # type: ignore[misc]


def test_audit_context_defaults():
    """AuditContext defaults to N/A for all fields."""
    ctx = AuditContext()
    assert ctx.client_ip == "N/A"
    assert ctx.method == "N/A"
    assert ctx.path == "N/A"


def test_audit_context_from_request():
    """AuditContext.from_request extracts request metadata."""
    req = _fake_request("10.0.0.1", "DELETE", "/api/x")
    ctx = AuditContext.from_request(req)
    assert ctx.client_ip == "10.0.0.1"
    assert ctx.method == "DELETE"
    assert ctx.path == "/api/x"


def test_audit_context_from_request_no_client():
    """AuditContext.from_request handles request.client=None."""
    req = _fake_request()
    req.client = None
    ctx = AuditContext.from_request(req)
    assert ctx.client_ip == "N/A"
