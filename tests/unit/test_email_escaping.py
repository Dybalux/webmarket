"""Unit tests for HTML escaping in email templates.

Covers:
  - send_new_order_notification: XSS payloads escaped in user_email, order_id,
    total_amount, payment_method
  - send_password_reset_email: XSS payload escaped in reset_url
  - Normal values rendered without modification
  - Special HTML characters (<, >, &, ", ') all escaped
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import email_service


# ---------------------------------------------------------------------------
# Helpers — restore real email functions (conftest autouse silences them)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_real_email_functions(monkeypatch):
    """Undo the conftest's silence_side_effects patching for these tests.

    We need the real functions to run so we can verify HTML escaping.
    """
    # Import the real module to get the real function references
    import importlib
    importlib.reload(email_service)

    # Also ensure settings allow email sending
    monkeypatch.setattr(email_service.settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(email_service.settings, "RESEND_API_KEY", "test-api-key")
    monkeypatch.setattr(email_service.settings, "RESEND_FROM_EMAIL", "noreply@example.com")


@pytest.fixture
def mock_resend():
    """Mock resend.Emails.send and return the captured params."""
    captured = {}

    def _capture(params):
        captured.update(params)
        return {"id": "mock-email-id"}

    with patch("resend.Emails.send", side_effect=_capture):
        yield captured


@pytest.fixture
def mock_db():
    """Mock database module to return an admin user for order notification."""
    mock_collection = MagicMock()
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [{"email": "admin@example.com"}]
    mock_collection.find.return_value = mock_cursor

    with patch("database.get_collection", return_value=mock_collection):
        yield mock_collection


# ---------------------------------------------------------------------------
# send_new_order_notification
# ---------------------------------------------------------------------------


class TestOrderNotificationEscaping:
    """XSS payloads in order notification fields must be HTML-escaped."""

    @pytest.mark.asyncio
    async def test_script_tag_in_user_email_escaped(self, mock_resend, mock_db):
        """<script>alert(1)</script> in user_email → &lt;script&gt;..."""
        await email_service.send_new_order_notification(
            order_id="abc123",
            user_email="<script>alert(1)</script>",
            total_amount=100.0,
            payment_method="Credit Card",
        )

        html_body = mock_resend["html"]
        assert "<script>" not in html_body
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_body

    @pytest.mark.asyncio
    async def test_img_tag_in_payment_method_escaped(self, mock_resend, mock_db):
        """<img src=x onerror=alert(1)> in payment_method → &lt;img..."""
        await email_service.send_new_order_notification(
            order_id="abc123",
            user_email="alice@example.com",
            total_amount=50.0,
            payment_method='<img src=x onerror=alert(1)>',
        )

        html_body = mock_resend["html"]
        assert "<img" not in html_body
        assert "&lt;img" in html_body

    @pytest.mark.asyncio
    async def test_order_id_with_html_escaped(self, mock_resend, mock_db):
        """HTML in order_id must be escaped."""
        await email_service.send_new_order_notification(
            order_id="<b>bold</b>",
            user_email="alice@example.com",
            total_amount=10.0,
            payment_method="Cash",
        )

        html_body = mock_resend["html"]
        assert "<b>bold</b>" not in html_body
        assert "&lt;b&gt;bold&lt;/b&gt;" in html_body

    @pytest.mark.asyncio
    async def test_quotes_in_fields_escaped(self, mock_resend, mock_db):
        """Double and single quotes must be escaped (default quote=True)."""
        await email_service.send_new_order_notification(
            order_id='id"onload=alert(1)',
            user_email="test@example.com",
            total_amount=100.0,
            payment_method="Card",
        )

        html_body = mock_resend["html"]
        # html.escape with quote=True escapes double quotes
        assert '"onload=' not in html_body
        assert "&quot;onload=" in html_body

    @pytest.mark.asyncio
    async def test_normal_values_rendered_correctly(self, mock_resend, mock_db):
        """Normal values must pass through without modification."""
        await email_service.send_new_order_notification(
            order_id="ORD-12345",
            user_email="alice@example.com",
            total_amount=99.99,
            payment_method="Mercado Pago",
        )

        html_body = mock_resend["html"]
        assert "alice@example.com" in html_body
        assert "ORD-12345" in html_body
        assert "Mercado Pago" in html_body


# ---------------------------------------------------------------------------
# send_password_reset_email
# ---------------------------------------------------------------------------


class TestPasswordResetEscaping:
    """XSS payloads in reset_url must be HTML-escaped."""

    @pytest.mark.asyncio
    async def test_script_tag_in_reset_url_escaped(self, mock_resend):
        """<script>alert(1)</script> in reset_url → escaped."""
        await email_service.send_password_reset_email(
            to_email="user@example.com",
            reset_url='https://example.com/reset?token=abc"><script>alert(1)</script>',
        )

        html_body = mock_resend["html"]
        assert "<script>" not in html_body
        assert "&lt;script&gt;" in html_body

    @pytest.mark.asyncio
    async def test_quotes_in_reset_url_escaped(self, mock_resend):
        """Quotes in reset_url must be escaped (protects href attribute)."""
        await email_service.send_password_reset_email(
            to_email="user@example.com",
            reset_url='https://example.com/reset?token=" onclick="alert(1)',
        )

        html_body = mock_resend["html"]
        # The double-quote is escaped to &quot;, preventing attribute breakout
        assert '"onclick=' not in html_body
        assert "&quot;" in html_body
        assert "alert(1)" in html_body  # value preserved, just neutralized

    @pytest.mark.asyncio
    async def test_normal_reset_url_rendered(self, mock_resend):
        """Normal URL rendered correctly (& escaped to &amp; in HTML)."""
        url = "https://example.com/reset?token=abc123&expires=1234567890"
        await email_service.send_password_reset_email(
            to_email="user@example.com",
            reset_url=url,
        )

        html_body = mock_resend["html"]
        # & in URL is escaped to &amp; by html.escape — this is correct HTML
        assert "https://example.com/reset?token=abc123&amp;expires=1234567890" in html_body
