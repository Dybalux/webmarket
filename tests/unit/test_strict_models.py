"""Unit tests for BaseRequestModel (extra="forbid").

Covers:
  - Extra field → ValidationError for all 12 request models
  - Valid payload passes for each model
  - AdminProduct (excluded from BaseRequestModel) still accepts extra fields
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

import os

from models import (
    Address,
    BulkPriceUpdate,
    CartItem,
    ComboCreate,
    ComboItem,
    ComboUpdate,
    DynamicPricingUpdate,
    ForgotPasswordRequest,
    OrderCreate,
    PasswordResetConfirm,
    PaymentSettingsUpdate,
    ProductUpdate,
    UserLogin,
    UserRegister,
    AdminProduct,
    UserResponse,
)


# ---------------------------------------------------------------------------
# Valid payloads — minimal but sufficient for each model
# ---------------------------------------------------------------------------

VALID_PAYLOADS: dict[str, tuple[type, dict]] = {
    "UserRegister": (
        UserRegister,
        {
            "username": "testuser",
            "email": "test@example.com",
            "password": "MyStr0ng!Pass99",
            "birth_date": "2000-01-01T00:00:00Z",
        },
    ),
    "UserLogin": (
        UserLogin,
        {"email_or_username": "test@example.com", "password": "secret"},
    ),
    "ForgotPasswordRequest": (
        ForgotPasswordRequest,
        {"email": "test@example.com"},
    ),
    "PasswordResetConfirm": (
        PasswordResetConfirm,
        {"token": "abc123", "new_password": "MyStr0ng!Pass99"},
    ),
    "OrderCreate": (
        OrderCreate,
        {
            "items": [{"product_id": "abc", "quantity": 1}],
            "shipping_address": {
                "street": "123 Main St",
                "city": "Springfield",
                "state": "IL",
                "zip_code": "62701",
                "country": "US",
            },
            "shipping_zone": "central",
        },
    ),
    "CartItem": (
        CartItem,
        {"product_id": "abc", "quantity": 2},
    ),
    "Address": (
        Address,
        {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip_code": "62701",
            "country": "US",
        },
    ),
    "BulkPriceUpdate": (
        BulkPriceUpdate,
        {"percentage": 0.10, "target": "all", "based_on": "price"},
    ),
    "ProductUpdate": (
        ProductUpdate,
        {"name": "Updated Name"},
    ),
    "ComboCreate": (
        ComboCreate,
        {
            "name": "Test Combo",
            "price": 100.0,
            "items": [{"product_id": "abc", "quantity": 1}],
        },
    ),
    "ComboUpdate": (
        ComboUpdate,
        {"name": "Updated Combo"},
    ),
    "ComboItem": (
        ComboItem,
        {"product_id": "abc", "quantity": 3},
    ),
    "PaymentSettingsUpdate": (
        PaymentSettingsUpdate,
        {
            "transfer_alias": "test.alias",
            "transfer_whatsapp": "+5491112345678",
        },
    ),
    "DynamicPricingUpdate": (
        DynamicPricingUpdate,
        {
            "enabled": True,
            "multiplier": 1.1,
            "start_day": 5,
            "end_day": 7,
            "start_hour": 20,
            "end_hour": 6,
        },
    ),
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStrictModelsRejectExtras:
    """Every BaseRequestModel subclass must reject unexpected fields with 422."""

    @pytest.mark.parametrize(
        "model_name",
        list(VALID_PAYLOADS.keys()),
        ids=list(VALID_PAYLOADS.keys()),
    )
    def test_extra_field_rejected(self, model_name: str) -> None:
        model_cls, valid_payload = VALID_PAYLOADS[model_name]
        payload_with_extra = {**valid_payload, "extra_field": "should_fail"}
        with pytest.raises(ValidationError) as exc_info:
            model_cls(**payload_with_extra)
        errors = exc_info.value.errors()
        assert any("extra" in str(e).lower() or "extra_field" in str(e) for e in errors), (
            f"{model_name}: expected extra-field rejection, got {errors}"
        )

    @pytest.mark.parametrize(
        "model_name",
        list(VALID_PAYLOADS.keys()),
        ids=list(VALID_PAYLOADS.keys()),
    )
    def test_valid_payload_accepted(self, model_name: str) -> None:
        model_cls, valid_payload = VALID_PAYLOADS[model_name]
        instance = model_cls(**valid_payload)
        assert instance is not None


class TestAdminProductNotStrict:
    """AdminProduct (excluded from BaseRequestModel) must still accept extra fields."""

    def test_admin_product_accepts_updated_at(self) -> None:
        """AdminProduct(**doc_with_updated_at) must validate — dual-use model."""
        doc = {
            "_id": "507f1f77bcf86cd799439011",
            "name": "Test Product",
            "price": 100.0,
            "category": "Cerveza",
            "stock": 10,
            "active": True,
            "updated_at": datetime.now(tz=timezone.utc),
        }
        # Should NOT raise — extra fields are allowed on AdminProduct
        product = AdminProduct(**doc)
        assert product.name == "Test Product"

    def test_admin_product_extra_field_allowed(self) -> None:
        """AdminProduct does NOT forbid extra fields."""
        doc = {
            "_id": "507f1f77bcf86cd799439011",
            "name": "Test Product",
            "price": 100.0,
            "category": "Cerveza",
            "stock": 10,
            "active": True,
            "unknown_field": "should_pass",
        }
        # Should NOT raise
        product = AdminProduct(**doc)
        assert product.name == "Test Product"


# ---------------------------------------------------------------------------
# S4.3: Settings ignores unknown env vars
# ---------------------------------------------------------------------------


class TestSettingsIgnoresUnknownEnvVars:
    """Settings(extra='ignore') must silently drop unknown env vars."""

    def test_unknown_env_var_does_not_raise(self, monkeypatch) -> None:
        """Settings() with a sentinel unknown env var must NOT raise."""
        monkeypatch.setenv("UNKNOWN_SENTINEL_VAR_FOOBAR", "bar")
        from config import Settings

        # Must not raise ValidationError or any other error
        s = Settings(
            SECRET_KEY="test-secret",
            DATABASE_URL="mongodb://localhost:27017",
            DATABASE_NAME="testdb",
            ENV="test",
        )
        # The unknown var must NOT appear as an attribute
        assert not hasattr(s, "UNKNOWN_SENTINEL_VAR_FOOBAR")

    def test_settings_extra_is_ignore(self) -> None:
        """Settings.model_config['extra'] must be 'ignore'."""
        from config import Settings

        assert Settings.model_config.get("extra") == "ignore"


# ---------------------------------------------------------------------------
# S4.4: Response models unaffected (accept extra fields)
# ---------------------------------------------------------------------------


class TestResponseModelsAcceptExtraFields:
    """Response models inherit from BaseModel (not BaseRequestModel) and must accept extra fields."""

    def test_user_response_accepts_extra_field(self) -> None:
        """UserResponse(**doc_with_extra) must NOT raise."""
        from bson import ObjectId

        doc = {
            "_id": ObjectId(),
            "username": "testuser",
            "email": "test@example.com",
            "role": "customer",
            "age_verified": True,
            "birth_date": "2000-01-01T00:00:00Z",
            "created_at": "2025-01-01T00:00:00Z",
            "extra_field": "should_pass",  # extra field
        }
        # Should NOT raise — response models do not forbid extras
        user = UserResponse(**doc)
        assert user.username == "testuser"
