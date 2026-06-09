"""Unit tests for the Pydantic models used by the stock-control surface.

Covers:
  * Product.stock field validation (ge=0)
  * InventoryAlert construction + JSON serialization
  * OrderItem and CartItem quantity validation (gt=0)

These are pure-Pydantic tests; they do not touch MongoDB, FastAPI, or the
network. Marked @pytest.mark.unit so they run in the fast tier.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from bson import ObjectId
from pydantic import ValidationError

from models import (
    CartItem,
    InventoryAlert,
    OrderItem,
    Product,
    ProductCategory,
)


# ---------------------------------------------------------------------------
# Product.stock validation
# ---------------------------------------------------------------------------

class TestProductStockValidation:
    @pytest.mark.unit
    def test_negative_stock_is_rejected(self):
        """Stock must be >= 0 per the Product model (Field(ge=0))."""
        with pytest.raises(ValidationError) as exc_info:
            Product(
                name="Quilmes 1L",
                price=1500.0,
                category=ProductCategory.BEER,
                stock=-1,
            )
        # The error must reference the stock field and the ge=0 constraint.
        errors = exc_info.value.errors()
        assert any(
            err["loc"] == ("stock",) and "greater than or equal to 0" in err["msg"].lower()
            for err in errors
        ), f"Expected stock ge=0 violation, got: {errors}"

    @pytest.mark.unit
    def test_zero_stock_is_accepted(self):
        """Zero is a valid stock value — represents sold-out but known SKU."""
        product = Product(
            name="Quilmes 1L",
            price=1500.0,
            category=ProductCategory.BEER,
            stock=0,
        )
        assert product.stock == 0

    @pytest.mark.unit
    def test_positive_stock_round_trips(self):
        product = Product(
            name="Quilmes 1L",
            price=1500.0,
            category=ProductCategory.BEER,
            stock=42,
        )
        assert product.stock == 42

    @pytest.mark.unit
    def test_explicit_zero_stock_constructs_with_id(self):
        """Sanity: optional id alias is honored when stock is zero."""
        oid = ObjectId()
        product = Product(
            _id=oid,
            name="Quilmes 1L",
            price=1500.0,
            category=ProductCategory.BEER,
            stock=0,
        )
        assert product.stock == 0


# ---------------------------------------------------------------------------
# InventoryAlert model
# ---------------------------------------------------------------------------

class TestInventoryAlertModel:
    @pytest.mark.unit
    def test_constructs_with_required_fields(self):
        alert = InventoryAlert(
            product_id="507f1f77bcf86cd799439011",
            product_name="Quilmes 1L",
            current_stock=8,
            threshold=10,
            message="El stock del producto 'Quilmes 1L' es bajo (8).",
        )
        assert alert.product_id == "507f1f77bcf86cd799439011"
        assert alert.product_name == "Quilmes 1L"
        assert alert.current_stock == 8
        assert alert.threshold == 10
        assert "Quilmes 1L" in alert.message
        # Default factory for timestamp
        assert isinstance(alert.timestamp, datetime)

    @pytest.mark.unit
    def test_serializes_to_json_compatible_dict(self):
        """InventoryAlert must round-trip through model_dump for storage."""
        alert = InventoryAlert(
            product_id="507f1f77bcf86cd799439011",
            product_name="Quilmes 1L",
            current_stock=10,
            threshold=10,
            message="bajo",
        )
        dumped = alert.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["product_id"] == "507f1f77bcf86cd799439011"
        assert dumped["current_stock"] == 10
        assert dumped["threshold"] == 10
        assert dumped["message"] == "bajo"
        assert "timestamp" in dumped


# ---------------------------------------------------------------------------
# CartItem / OrderItem quantity validation
# ---------------------------------------------------------------------------

class TestCartItemQuantityValidation:
    @pytest.mark.unit
    def test_zero_quantity_is_rejected(self):
        """CartItem.quantity has gt=0; zero is not a valid cart line."""
        with pytest.raises(ValidationError) as exc_info:
            CartItem(product_id="507f1f77bcf86cd799439011", quantity=0)
        errors = exc_info.value.errors()
        assert any(err["loc"] == ("quantity",) for err in errors)

    @pytest.mark.unit
    def test_negative_quantity_is_rejected(self):
        with pytest.raises(ValidationError):
            CartItem(product_id="507f1f77bcf86cd799439011", quantity=-3)

    @pytest.mark.unit
    def test_positive_quantity_is_accepted(self):
        item = CartItem(product_id="507f1f77bcf86cd799439011", quantity=3)
        assert item.quantity == 3
        assert item.product_id == "507f1f77bcf86cd799439011"


class TestOrderItemQuantityValidation:
    @pytest.mark.unit
    def test_zero_quantity_is_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            OrderItem(
                product_id=ObjectId("507f1f77bcf86cd799439011"),
                name="Quilmes 1L",
                quantity=0,
                price_at_purchase=1500.0,
            )
        errors = exc_info.value.errors()
        assert any(err["loc"] == ("quantity",) for err in errors)

    @pytest.mark.unit
    def test_positive_quantity_is_accepted(self):
        item = OrderItem(
            product_id=ObjectId("507f1f77bcf86cd799439011"),
            name="Quilmes 1L",
            quantity=2,
            price_at_purchase=1500.0,
        )
        assert item.quantity == 2
        assert item.price_at_purchase == 1500.0
