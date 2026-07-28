"""Tests for monetary precision: Money validator, Decimal128 round-trip,
and integration scenarios (order total, bulk-update, range filter, revenue sum).

Covers:
  * Money validator rejects Python float
  * Money validator accepts string and Decimal
  * Money validator accepts Decimal128 (DB reads)
  * quantize_money with ROUND_HALF_UP
  * decimalize_doc recursive conversion
  * from_decimal128 legacy float handling
  * mongomock-motor Decimal128 round-trip (spike)
  * Integration: order total accumulation (100 × 19.99 = 1999.00)
  * Integration: bulk price update (500 × 1.10 = 550.00)
  * Integration: product range filter on Decimal128
  * Integration: revenue $sum without drift

Marked @pytest.mark.unit for the fast tier; integration tests use test fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from bson import Decimal128, ObjectId
from pydantic import BaseModel, ValidationError

from utils.money import (
    Money,
    decimalize_doc,
    from_decimal128,
    quantize_money,
    to_decimal128,
)


# ---------------------------------------------------------------------------
# Money validator tests (task 1.5)
# ---------------------------------------------------------------------------


class _MoneyTestModel(BaseModel):
    """Minimal model for testing the Money annotated type."""
    amount: Money


class TestMoneyValidator:
    """Pydantic field_validator: reject float, accept str/Decimal/Decimal128."""

    @pytest.mark.unit
    def test_accepts_string_input(self):
        """Money field MUST accept string like "19.99"."""
        m = _MoneyTestModel(amount="19.99")
        assert m.amount == Decimal("19.99")

    @pytest.mark.unit
    def test_accepts_decimal_input(self):
        """Money field MUST accept Decimal directly."""
        m = _MoneyTestModel(amount=Decimal("1500.00"))
        assert m.amount == Decimal("1500.00")

    @pytest.mark.unit
    def test_accepts_integer_input(self):
        """Money field MUST accept integer (coerced to Decimal)."""
        m = _MoneyTestModel(amount=1500)
        assert m.amount == Decimal("1500")

    @pytest.mark.unit
    def test_rejects_float_input(self):
        """Money field MUST reject Python float to prevent binary noise."""
        with pytest.raises(ValidationError) as exc_info:
            _MoneyTestModel(amount=19.99)
        errors = exc_info.value.errors()
        assert any("float" in err["msg"].lower() for err in errors)

    @pytest.mark.unit
    def test_rejects_float_zero(self):
        """Even float(0.0) must be rejected — use Decimal("0.00") instead."""
        with pytest.raises(ValidationError):
            _MoneyTestModel(amount=0.0)

    @pytest.mark.unit
    def test_accepts_decimal128_input(self):
        """Money field MUST accept bson.Decimal128 (DB read path)."""
        d128 = Decimal128("1234.56")
        m = _MoneyTestModel(amount=d128)
        assert m.amount == Decimal("1234.56")

    @pytest.mark.unit
    def test_precision_preserved_two_places(self):
        """Money field MUST preserve exactly 2 decimal places."""
        m = _MoneyTestModel(amount="19.99")
        # Decimal quantized to 2 dp
        assert m.amount == Decimal("19.99")
        assert m.amount.as_tuple().exponent == -2

    @pytest.mark.unit
    def test_json_serialization_as_string(self):
        """Pydantic v2 MUST serialize Decimal as string in JSON."""
        m = _MoneyTestModel(amount=Decimal("1234.56"))
        dumped = m.model_dump(mode="json")
        assert dumped["amount"] == "1234.56"


# ---------------------------------------------------------------------------
# quantize_money tests (task 1.3)
# ---------------------------------------------------------------------------


class TestQuantizeMoney:
    """ROUND_HALF_UP quantization to 2 decimal places."""

    @pytest.mark.unit
    def test_rounds_half_up(self):
        """19.995 → 20.00 (ROUND_HALF_UP)."""
        assert quantize_money(Decimal("19.995")) == Decimal("20.00")

    @pytest.mark.unit
    def test_rounds_down(self):
        """19.994 → 19.99."""
        assert quantize_money(Decimal("19.994")) == Decimal("19.99")

    @pytest.mark.unit
    def test_already_quantized(self):
        """19.99 → 19.99 (no-op)."""
        assert quantize_money(Decimal("19.99")) == Decimal("19.99")

    @pytest.mark.unit
    def test_classic_float_trap(self):
        """0.1 + 0.2 = 0.3 in Decimal (quantized)."""
        result = quantize_money(Decimal("0.1") + Decimal("0.2"))
        assert result == Decimal("0.30")

    @pytest.mark.unit
    def test_large_multiplication(self):
        """100 * 19.99 = 1999.00 (no drift)."""
        result = quantize_money(Decimal("100") * Decimal("19.99"))
        assert result == Decimal("1999.00")

    @pytest.mark.unit
    def test_bulk_price_update_semantics(self):
        """500.00 * (1 + 0.10) = 550.00 exactly (ADR-4 fraction semantics)."""
        base = Decimal("500.00")
        percentage = Decimal("0.10")
        result = quantize_money(base * (Decimal("1") + percentage))
        assert result == Decimal("550.00")


# ---------------------------------------------------------------------------
# to_decimal128 / from_decimal128 round-trip tests (task 1.2)
# ---------------------------------------------------------------------------


class TestDecimal128Conversion:
    """Explicit Decimal ↔ Decimal128 conversion (ADR-2)."""

    @pytest.mark.unit
    def test_to_decimal128(self):
        """Decimal → Decimal128 preserves value."""
        d = Decimal("1234.56")
        d128 = to_decimal128(d)
        assert isinstance(d128, Decimal128)
        assert str(d128) == "1234.56"

    @pytest.mark.unit
    def test_from_decimal128(self):
        """Decimal128 → Decimal preserves value."""
        d128 = Decimal128("1234.56")
        d = from_decimal128(d128)
        assert isinstance(d, Decimal)
        assert d == Decimal("1234.56")

    @pytest.mark.unit
    def test_round_trip(self):
        """Decimal → Decimal128 → Decimal is lossless."""
        original = Decimal("99999999.99")
        result = from_decimal128(to_decimal128(original))
        assert result == original

    @pytest.mark.unit
    def test_from_decimal128_handles_legacy_float(self):
        """from_decimal128 MUST handle legacy float docs via str() coercion."""
        result = from_decimal128(1234.56)
        assert isinstance(result, Decimal)
        # str(1234.56) → "1234.56" → Decimal("1234.56")
        assert result == Decimal("1234.56")

    @pytest.mark.unit
    def test_from_decimal128_handles_decimal_passthrough(self):
        """from_decimal128 MUST pass through Decimal unchanged."""
        d = Decimal("100.00")
        assert from_decimal128(d) == d


# ---------------------------------------------------------------------------
# decimalize_doc tests (task 1.1)
# ---------------------------------------------------------------------------


class TestDecimalizeDoc:
    """Recursive Decimal → Decimal128 conversion for MongoDB writes."""

    @pytest.mark.unit
    def test_converts_decimal_fields(self):
        doc = {"price": Decimal("19.99"), "name": "Quilmes"}
        result = decimalize_doc(doc)
        assert isinstance(result["price"], Decimal128)
        assert str(result["price"]) == "19.99"
        assert result["name"] == "Quilmes"

    @pytest.mark.unit
    def test_handles_nested_dict(self):
        doc = {"item": {"price": Decimal("100.00")}}
        result = decimalize_doc(doc)
        assert isinstance(result["item"]["price"], Decimal128)

    @pytest.mark.unit
    def test_handles_list_of_dicts(self):
        doc = {"items": [{"price": Decimal("10.00")}, {"price": Decimal("20.00")}]}
        result = decimalize_doc(doc)
        assert isinstance(result["items"][0]["price"], Decimal128)
        assert isinstance(result["items"][1]["price"], Decimal128)

    @pytest.mark.unit
    def test_non_decimal_values_pass_through(self):
        doc = {"name": "Test", "stock": 10, "active": True}
        result = decimalize_doc(doc)
        assert result == {"name": "Test", "stock": 10, "active": True}


# ---------------------------------------------------------------------------
# mongomock-motor Decimal128 round-trip spike (task 1.6)
# ---------------------------------------------------------------------------


class TestMongomockDecimal128Spike:
    """Verify mongomock-motor supports Decimal128 round-trip.

    This is a spike test — if it fails, we need to upgrade mongomock or
    wrap at the mock boundary.
    """

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_decimal128_round_trip_in_mongomock(self, reset_db_singleton):
        """Write Decimal128, read it back — value must survive."""
        db = reset_db_singleton
        collection = db["test_decimal_spike"]

        # Write with Decimal128
        doc = {
            "name": "spike-test",
            "total_amount": Decimal128("1234.56"),
            "price": Decimal128("99.99"),
        }
        await collection.insert_one(doc)

        # Read back
        result = await collection.find_one({"name": "spike-test"})
        assert result is not None

        # Verify types survived
        assert isinstance(result["total_amount"], Decimal128)
        assert isinstance(result["price"], Decimal128)

        # Verify values
        assert from_decimal128(result["total_amount"]) == Decimal("1234.56")
        assert from_decimal128(result["price"]) == Decimal("99.99")

    @pytest.mark.asyncio
    @pytest.mark.unit
    @pytest.mark.xfail(
        reason="mongomock-motor does not support Decimal128 in $gte/$lte comparisons",
        raises=NotImplementedError,
        strict=True,
    )
    async def test_decimal128_sorting_works(self, reset_db_singleton):
        """Decimal128 MUST sort numerically (gte/lte queries).

        NOTE: mongomock-motor 0.0.36 does not support Decimal128 comparisons.
        This test verifies the limitation exists. In production (real MongoDB),
        Decimal128 sorts correctly. The service layer uses real Motor.
        """
        db = reset_db_singleton
        collection = db["test_decimal_sort"]

        await collection.insert_many([
            {"price": Decimal128("100.00")},
            {"price": Decimal128("50.00")},
            {"price": Decimal128("200.00")},
        ])

        # Find prices >= 100
        cursor = collection.find({"price": {"$gte": Decimal128("100.00")}})
        results = await cursor.to_list(None)
        assert len(results) == 2
        prices = [from_decimal128(r["price"]) for r in results]
        assert Decimal("100.00") in prices
        assert Decimal("200.00") in prices


# ---------------------------------------------------------------------------
# Integration tests — Decimal precision through service layers (task 3.7)
# ---------------------------------------------------------------------------


class TestDecimalIntegrationOrderTotal:
    """Order total accumulation must be exact (spec: 100 × 19.99 = 1999.00)."""

    @pytest.mark.asyncio
    async def test_order_total_exact_accumulation(self, test_db):
        """100 units at Decimal('19.99') each → total = Decimal('1999.00')."""
        from utils.money import quantize_money

        price = Decimal("19.99")
        quantity = 100
        total = quantize_money(price * Decimal(str(quantity)))
        assert total == Decimal("1999.00")

    @pytest.mark.asyncio
    async def test_order_total_stored_as_decimal128(self, test_db):
        """Order total written to MongoDB must be Decimal128."""
        orders = test_db["orders"]
        total = quantize_money(Decimal("19.99") * Decimal("100"))
        doc = {
            "user_id": "test_user",
            "items": [],
            "total_amount": total,
            "status": "Pendiente",
            "shipping_address": {
                "street": "123 Main St",
                "city": "Springfield",
                "state": "IL",
                "zip_code": "62701",
                "country": "US",
            },
            "created_at": datetime.now(tz=timezone.utc),
        }
        await orders.insert_one(decimalize_doc(doc))

        stored = await orders.find_one({"user_id": "test_user"})
        assert isinstance(stored["total_amount"], Decimal128)
        assert from_decimal128(stored["total_amount"]) == Decimal("1999.00")

    @pytest.mark.asyncio
    async def test_classic_float_trap_avoided(self, test_db):
        """Decimal('0.1') + Decimal('0.2') = Decimal('0.30') in order context."""
        total = quantize_money(Decimal("0.1") + Decimal("0.2"))
        assert total == Decimal("0.30")


class TestDecimalIntegrationBulkUpdate:
    """Bulk price update: 500 × (1 + 0.10) = 550.00 exactly (ADR-4)."""

    @pytest.mark.asyncio
    async def test_bulk_update_preserves_precision(self, test_db):
        """Bulk price update with fraction semantics (0.10 = 10%)."""
        products = test_db["products"]
        product = await products.find_one({"_id": ObjectId("507f1f77bcf86cd799439011")})
        assert product is not None

        base_price = from_decimal128(product["price"])
        percentage = Decimal("0.10")
        new_price = quantize_money(base_price * (Decimal("1") + percentage))

        await products.update_one(
            {"_id": product["_id"]},
            {"$set": decimalize_doc({"price": new_price})},
        )

        updated = await products.find_one({"_id": product["_id"]})
        assert isinstance(updated["price"], Decimal128)
        assert from_decimal128(updated["price"]) == quantize_money(
            Decimal("1500.00") * Decimal("1.10")
        )

    @pytest.mark.asyncio
    async def test_bulk_update_net_price_based(self, test_db):
        """Bulk update based on net_price (costo) preserves Decimal precision."""
        products = test_db["products"]
        # Insert a product with net_price
        await products.insert_one(decimalize_doc({
            "_id": ObjectId("507f1f77bcf86cd799439099"),
            "name": "Test Bulk Product",
            "price": Decimal("1000.00"),
            "net_price": Decimal("500.00"),
            "category": "Cerveza",
            "stock": 10,
            "active": True,
        }))

        product = await products.find_one({"_id": ObjectId("507f1f77bcf86cd799439099")})
        base = from_decimal128(product["net_price"])
        percentage = Decimal("0.10")
        new_price = quantize_money(base * (Decimal("1") + percentage))
        assert new_price == Decimal("550.00")

        await products.update_one(
            {"_id": product["_id"]},
            {"$set": decimalize_doc({"price": new_price})},
        )
        updated = await products.find_one({"_id": product["_id"]})
        assert from_decimal128(updated["price"]) == Decimal("550.00")


class TestDecimalIntegrationRangeFilter:
    """Product range filter on Decimal128 values.

    NOTE: mongomock-motor 0.0.36 does not support Decimal128 $gte/$lte.
    These tests use direct Decimal comparison logic (service-layer pattern)
    to verify the conversion pipeline works end-to-end.
    """

    @pytest.mark.asyncio
    async def test_products_stored_as_decimal128(self, test_db):
        """All seeded product prices must be Decimal128 in MongoDB."""
        products = test_db["products"]
        async for doc in products.find({}):
            assert isinstance(doc["price"], Decimal128), (
                f"Product {doc['name']} price is {type(doc['price'])}, expected Decimal128"
            )

    @pytest.mark.asyncio
    async def test_from_decimal128_conversion_for_range(self, test_db):
        """from_decimal128 conversion enables correct range comparison."""
        products = test_db["products"]
        min_price = Decimal("1000.00")
        max_price = Decimal("5000.00")

        all_products = await products.find({}).to_list(None)
        in_range = [
            p for p in all_products
            if min_price <= from_decimal128(p["price"]) <= max_price
        ]
        # Quilmes 1500, Stella 2200, Malbec 4200 are in range; Fernet 8500 is not
        names = {p["name"] for p in in_range}
        assert "Quilmes 1L" in names
        assert "Stella Artois 1L" in names
        assert "Vino Malbec 750ml" in names
        assert "Fernet Branca 750ml" not in names


class TestDecimalIntegrationRevenueSum:
    """Revenue $sum aggregation must not lose precision.

    Uses manual Decimal sum (same as MongoDB $sum over Decimal128 would do)
    because mongomock-motor does not support $sum over Decimal128.
    """

    @pytest.mark.asyncio
    async def test_revenue_sum_no_drift(self, test_db):
        """Sum of order totals must be exact Decimal (no float drift)."""
        orders = test_db["orders"]

        # Insert delivered orders with Decimal128 totals
        totals = [Decimal("1999.00"), Decimal("500.00"), Decimal("2500.50")]
        for i, total in enumerate(totals):
            await orders.insert_one(decimalize_doc({
                "_id": ObjectId(),
                "user_id": "test_user",
                "items": [],
                "total_amount": total,
                "status": "Entregado",
                "shipping_address": {
                    "street": "123 Main St",
                    "city": "Springfield",
                    "state": "IL",
                    "zip_code": "62701",
                    "country": "US",
                },
                "created_at": datetime.now(tz=timezone.utc),
            }))

        # Read back and sum (simulates $sum pipeline)
        delivered = await orders.find({"status": "Entregado"}).to_list(None)
        revenue = sum(
            (from_decimal128(doc["total_amount"]) for doc in delivered),
            Decimal("0.00"),
        )
        revenue = quantize_money(revenue)
        assert revenue == Decimal("4999.50")

    @pytest.mark.asyncio
    async def test_revenue_sum_with_zero(self, test_db):
        """Revenue from no orders = Decimal('0.00')."""
        orders = test_db["orders"]
        delivered = await orders.find({"status": "Entregado"}).to_list(None)
        revenue = sum(
            (from_decimal128(doc["total_amount"]) for doc in delivered),
            Decimal("0.00"),
        )
        revenue = quantize_money(revenue)
        assert revenue == Decimal("0.00")
