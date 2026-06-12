"""Unit tests for the low-stock alert logic in routers/inventory.py.

Covers `check_and_create_alert`:
  * Alert created at the threshold boundary (stock=10)
  * No alert above the threshold (stock=15)
  * Duplicate alert prevention (same product_id + same message)

Marked @pytest.mark.unit. No FastAPI, no TestClient — these tests call the
helper directly with a mongomock-motor collection pair so we can assert
document state without the HTTP layer.
"""

from __future__ import annotations

import pytest
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from services.inventory import LOW_STOCK_THRESHOLD, check_and_create_alert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_db():
    """Return a fresh mongomock database with pre-seeded product collections."""
    client = AsyncMongoMockClient()
    return client["webmarket_test"]


async def _seed_product(products_coll, *, name: str, stock: int) -> ObjectId:
    oid = ObjectId()
    await products_coll.insert_one(
        {
            "_id": oid,
            "name": name,
            "description": name,
            "price": 1500.0,
            "category": "Cerveza",
            "stock": stock,
            "active": True,
        }
    )
    return oid


# ---------------------------------------------------------------------------
# Threshold behavior
# ---------------------------------------------------------------------------

class TestCheckAndCreateAlert:
    @pytest.mark.unit
    async def test_alert_created_at_threshold(self):
        """stock == LOW_STOCK_THRESHOLD → alert is inserted."""
        db = _fresh_db()
        products = db["products"]
        alerts = db["inventory_alerts"]
        oid = await _seed_product(products, name="Quilmes 1L", stock=LOW_STOCK_THRESHOLD)

        await check_and_create_alert(db, str(oid))

        inserted = await alerts.find_one({"product_id": str(oid)})
        assert inserted is not None
        assert inserted["current_stock"] == LOW_STOCK_THRESHOLD
        assert inserted["threshold"] == LOW_STOCK_THRESHOLD
        assert "Quilmes 1L" in inserted["message"]

    @pytest.mark.unit
    async def test_no_alert_above_threshold(self):
        """stock > LOW_STOCK_THRESHOLD → no alert inserted."""
        db = _fresh_db()
        products = db["products"]
        alerts = db["inventory_alerts"]
        oid = await _seed_product(products, name="Stella 1L", stock=15)

        await check_and_create_alert(db, str(oid))

        count = await alerts.count_documents({"product_id": str(oid)})
        assert count == 0

    @pytest.mark.unit
    async def test_alert_created_well_below_threshold(self):
        """stock << LOW_STOCK_THRESHOLD → alert is inserted."""
        db = _fresh_db()
        products = db["products"]
        alerts = db["inventory_alerts"]
        oid = await _seed_product(products, name="Fernet 750ml", stock=2)

        await check_and_create_alert(db, str(oid))

        inserted = await alerts.find_one({"product_id": str(oid)})
        assert inserted is not None
        assert inserted["current_stock"] == 2
        assert inserted["threshold"] == LOW_STOCK_THRESHOLD

    @pytest.mark.unit
    async def test_no_alert_for_missing_product(self):
        """Missing product → no alert (function silently returns)."""
        db = _fresh_db()
        products = db["products"]
        alerts = db["inventory_alerts"]
        missing_id = str(ObjectId())

        # Should not raise.
        await check_and_create_alert(db, missing_id)

        count = await alerts.count_documents({"product_id": missing_id})
        assert count == 0


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestAlertDeduplication:
    @pytest.mark.unit
    async def test_duplicate_alert_for_same_stock_level_not_created(self):
        """A second call for the same product with the same stock must not insert again.

        The dedup key is (product_id, message). The message is built from the
        current stock value, so when stock is unchanged the message is
        identical and the second call must short-circuit.
        """
        db = _fresh_db()
        products = db["products"]
        alerts = db["inventory_alerts"]
        oid = await _seed_product(products, name="Quilmes 1L", stock=8)

        # First call → alert inserted.
        await check_and_create_alert(db, str(oid))
        first_count = await alerts.count_documents({"product_id": str(oid)})
        assert first_count == 1

        # Second call (no stock change) → no new alert.
        await check_and_create_alert(db, str(oid))
        second_count = await alerts.count_documents({"product_id": str(oid)})
        assert second_count == 1

    @pytest.mark.unit
    async def test_new_alert_inserted_when_stock_changes(self):
        """If stock drops, the message changes, so a new alert is created."""
        db = _fresh_db()
        products = db["products"]
        alerts = db["inventory_alerts"]
        oid = await _seed_product(products, name="Quilmes 1L", stock=8)

        # First alert at stock=8
        await check_and_create_alert(db, str(oid))
        # Stock drops to 5 → message changes
        await products.update_one({"_id": oid}, {"$set": {"stock": 5}})
        await check_and_create_alert(db, str(oid))

        count = await alerts.count_documents({"product_id": str(oid)})
        assert count == 2
        # The two messages should be different (the stock number changed).
        messages = [
            doc["message"]
            async for doc in alerts.find({"product_id": str(oid)})
        ]
        assert len(set(messages)) == 2
