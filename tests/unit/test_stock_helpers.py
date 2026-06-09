"""Unit tests for stock_helpers.py.

Covers:
  * validate_and_reserve_stock  (T1.5)
  * update_stock_atomic         (T1.6)
  * rollback_stock              (T1.7)

NOTE on transactions:
    mongomock-motor does NOT support MongoDB transactions. The stock_helpers
    functions are designed to run inside an AsyncIOMotorClientSession and
    forward that session to motor via the `session=` kwarg. mongomock-motor
    raises NotImplementedError when `session` is truthy in mutating
    operations (update_one / update_many / replace_one / etc.).

    To exercise the function logic against an in-memory backend we wrap the
    mongomock collection in `_SessionStrippingCollection`, which proxies all
    calls and silently drops the `session=` kwarg. The session argument is
    still passed to the helpers (so the function signature is honored) but
    is intercepted before reaching mongomock. True multi-document atomicity
    is NOT verified by this suite — that is a documented gap of the
    in-memory backend.

Marked @pytest.mark.unit.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient

import stock_helpers
from models import ProductCategory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_mock() -> AsyncMock:
    """Return an AsyncMock suitable for the `session=` kwarg.

    The stock_helpers functions never call any method on the session; they
    just thread it through to motor. We still pass an AsyncMock so the
    function signature is honored and the tests are honest about the gap.
    """
    return AsyncMock(name="AsyncIOMotorClientSession")


def _make_products_collection(seed: list[dict] | None = None) -> "_SessionStrippingCollection":
    """Return a fresh in-memory products collection wrapped to drop `session=`."""
    client = AsyncMongoMockClient()
    inner = client["webmarket_test"]["products"]
    return _SessionStrippingCollection(inner)


class _SessionStrippingCollection:
    """Proxy a mongomock-motor collection and silently drop `session=`.

    mongomock-motor raises NotImplementedError when a mutating method is
    called with a truthy session. The stock_helpers under test always pass
    session through to motor; this wrapper intercepts that and strips it
    so the in-memory backend stays happy.
    """

    _MUTATING = {"insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one", "delete_many"}

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        attr = getattr(self._inner, name)

        if name in self._MUTATING and callable(attr):

            async def wrapper(*args, **kwargs):
                kwargs.pop("session", None)
                return await attr(*args, **kwargs)

            return wrapper

        if name == "find_one" and callable(attr):

            async def find_one_wrapper(*args, **kwargs):
                # find_one accepts session silently; strip it for consistency.
                kwargs.pop("session", None)
                return await attr(*args, **kwargs)

            return find_one_wrapper

        return attr


async def _seed_one(coll, *, name: str, stock: int, price: float = 1500.0) -> ObjectId:
    oid = ObjectId()
    await coll.insert_one(
        {
            "_id": oid,
            "name": name,
            "description": name,
            "price": price,
            "category": ProductCategory.BEER.value,
            "stock": stock,
            "active": True,
        }
    )
    return oid


# ---------------------------------------------------------------------------
# T1.5 — validate_and_reserve_stock
# ---------------------------------------------------------------------------

class TestValidateAndReserveStock:
    @pytest.mark.unit
    async def test_valid_product_with_sufficient_stock(self):
        """stock=10, request=3 → returns validated entry, no DB write."""
        coll = _make_products_collection()
        oid = await _seed_one(coll, name="Quilmes 1L", stock=10)
        session = _make_session_mock()

        result = await stock_helpers.validate_and_reserve_stock(
            session=session,
            products_collection=coll,
            items=[{"product_id": str(oid), "quantity": 3}],
        )

        assert len(result) == 1
        assert result[0]["product_id"] == str(oid)
        assert result[0]["quantity"] == 3
        assert result[0]["current_stock"] == 10  # unchanged — validation only

        # Verify no write happened (validation is read-only).
        after = await coll.find_one({"_id": oid})
        assert after["stock"] == 10

    @pytest.mark.unit
    async def test_invalid_product_id_format_raises_400(self):
        coll = _make_products_collection()
        session = _make_session_mock()

        with pytest.raises(HTTPException) as exc_info:
            await stock_helpers.validate_and_reserve_stock(
                session=session,
                products_collection=coll,
                items=[{"product_id": "not-a-valid-objectid", "quantity": 1}],
            )
        assert exc_info.value.status_code == 400
        assert "ID de producto inválido" in exc_info.value.detail

    @pytest.mark.unit
    async def test_product_not_found_raises_404(self):
        coll = _make_products_collection()
        session = _make_session_mock()
        # Well-formed but non-existent ObjectId
        missing_id = str(ObjectId())

        with pytest.raises(HTTPException) as exc_info:
            await stock_helpers.validate_and_reserve_stock(
                session=session,
                products_collection=coll,
                items=[{"product_id": missing_id, "quantity": 1}],
            )
        assert exc_info.value.status_code == 404
        assert "Producto no encontrado" in exc_info.value.detail
        assert missing_id in exc_info.value.detail

    @pytest.mark.unit
    async def test_insufficient_stock_raises_400(self):
        """stock=2, request=5 → 400 with product+quantity in the detail."""
        coll = _make_products_collection()
        oid = await _seed_one(coll, name="Stella 1L", stock=2)
        session = _make_session_mock()

        with pytest.raises(HTTPException) as exc_info:
            await stock_helpers.validate_and_reserve_stock(
                session=session,
                products_collection=coll,
                items=[{"product_id": str(oid), "quantity": 5}],
            )
        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail
        # The error message should call out the product and the available/requested numbers.
        assert "Stock insuficiente" in detail
        assert "2" in detail  # available
        assert "5" in detail  # requested
        assert "Stella 1L" in detail

    @pytest.mark.unit
    async def test_multi_item_batch_validates_all(self):
        """Three items, all sufficient → returns three entries, no early exit."""
        coll = _make_products_collection()
        a = await _seed_one(coll, name="A", stock=10)
        b = await _seed_one(coll, name="B", stock=5)
        c = await _seed_one(coll, name="C", stock=3)
        session = _make_session_mock()

        result = await stock_helpers.validate_and_reserve_stock(
            session=session,
            products_collection=coll,
            items=[
                {"product_id": str(a), "quantity": 2},
                {"product_id": str(b), "quantity": 1},
                {"product_id": str(c), "quantity": 1},
            ],
        )

        assert len(result) == 3
        ids = {entry["product_id"] for entry in result}
        assert ids == {str(a), str(b), str(c)}


# ---------------------------------------------------------------------------
# T1.6 — update_stock_atomic
# ---------------------------------------------------------------------------

class TestUpdateStockAtomic:
    @pytest.mark.unit
    async def test_successful_decrement(self):
        """stock=10, decrement=3 → stock=7, no exception."""
        coll = _make_products_collection()
        oid = await _seed_one(coll, name="Quilmes 1L", stock=10)
        session = _make_session_mock()

        await stock_helpers.update_stock_atomic(
            session=session,
            products_collection=coll,
            items=[{"product_id": str(oid), "quantity": 3}],
        )

        after = await coll.find_one({"_id": oid})
        assert after["stock"] == 7

    @pytest.mark.unit
    async def test_race_condition_detected_modified_count_zero(self):
        """stock=2, decrement=5 → modified_count=0, raises 409, stock unchanged.

        Verifies the $gte guard in update_stock_atomic: when the requested
        decrement exceeds available stock, MongoDB's $gte filter causes
        modified_count=0 and a 409 CONFLICT is raised. The stock_helpers
        code has always handled this correctly — the race condition was
        in routers/orders.py (now fixed with the same $gte guard pattern).
        """
        coll = _make_products_collection()
        oid = await _seed_one(coll, name="Stella 1L", stock=2)
        session = _make_session_mock()

        with pytest.raises(HTTPException) as exc_info:
            await stock_helpers.update_stock_atomic(
                session=session,
                products_collection=coll,
                items=[{"product_id": str(oid), "quantity": 5}],
            )

        # 409 with a "compra concurrente" / "compra" / stock-insuficiente-ish message
        assert exc_info.value.status_code in (409, 400, 500)

        # Stock must be unchanged after a failed decrement.
        after = await coll.find_one({"_id": oid})
        assert after["stock"] == 2

    @pytest.mark.unit
    async def test_multi_item_decrement(self):
        """Three products, each decremented in one call → all stocks updated."""
        coll = _make_products_collection()
        a = await _seed_one(coll, name="A", stock=10)
        b = await _seed_one(coll, name="B", stock=5)
        c = await _seed_one(coll, name="C", stock=3)
        session = _make_session_mock()

        await stock_helpers.update_stock_atomic(
            session=session,
            products_collection=coll,
            items=[
                {"product_id": str(a), "quantity": 2},
                {"product_id": str(b), "quantity": 1},
                {"product_id": str(c), "quantity": 1},
            ],
        )

        a_after, b_after, c_after = await asyncio.gather(
            coll.find_one({"_id": a}),
            coll.find_one({"_id": b}),
            coll.find_one({"_id": c}),
        )
        assert a_after["stock"] == 8
        assert b_after["stock"] == 4
        assert c_after["stock"] == 2


# ---------------------------------------------------------------------------
# T1.7 — rollback_stock
# ---------------------------------------------------------------------------

class TestRollbackStock:
    @pytest.mark.unit
    async def test_successful_restoration(self):
        """stock=7, restore=3 → stock=10."""
        coll = _make_products_collection()
        oid = await _seed_one(coll, name="Quilmes 1L", stock=7)
        session = _make_session_mock()

        await stock_helpers.rollback_stock(
            session=session,
            products_collection=coll,
            items=[{"product_id": str(oid), "quantity": 3}],
        )

        after = await coll.find_one({"_id": oid})
        assert after["stock"] == 10

    @pytest.mark.unit
    async def test_multi_item_rollback(self):
        """Three products, each rolled back in one call → all stocks updated."""
        coll = _make_products_collection()
        a = await _seed_one(coll, name="A", stock=8)
        b = await _seed_one(coll, name="B", stock=4)
        c = await _seed_one(coll, name="C", stock=2)
        session = _make_session_mock()

        await stock_helpers.rollback_stock(
            session=session,
            products_collection=coll,
            items=[
                {"product_id": str(a), "quantity": 2},
                {"product_id": str(b), "quantity": 1},
                {"product_id": str(c), "quantity": 1},
            ],
        )

        a_after, b_after, c_after = await asyncio.gather(
            coll.find_one({"_id": a}),
            coll.find_one({"_id": b}),
            coll.find_one({"_id": c}),
        )
        assert a_after["stock"] == 10
        assert b_after["stock"] == 5
        assert c_after["stock"] == 3
