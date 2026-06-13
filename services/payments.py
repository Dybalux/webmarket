"""Payment business logic — Mercado Pago integration.

Public API (see design §2.6):
  - create_mp_preference(db, user_id, order_id) -> dict
  - process_webhook(db, topic, payment_id, x_signature, x_request_id) -> None

Idempotent webhook: the same payment_id can be processed multiple times safely.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from functools import lru_cache
from typing import Optional

import mercadopago
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from config import settings
from models import OrderStatus
from services.exceptions import (
    ForbiddenError,
    InvalidStateTransitionError,
    NotFoundError,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_sdk() -> mercadopago.SDK:
    """Return the cached MercadoPago SDK client.

    Initialised lazily so the module can be imported (and /health can
    respond) in environments where MERCADOPAGO_ACCESS_TOKEN is not set
    (CI smoke tests, local dev without secrets). A clear error is raised
    only when a payment call actually runs without a configured token.
    """
    token = settings.MERCADOPAGO_ACCESS_TOKEN
    if not token:
        raise RuntimeError(
            "MERCADOPAGO_ACCESS_TOKEN is not configured. "
            "Set it in the environment or .env to use payment endpoints."
        )
    return mercadopago.SDK(token)


async def create_mp_preference(
    db: AsyncIOMotorDatabase, user_id: str, order_id: str,
) -> dict:
    """Create a Mercado Pago preference, returning {preference_id, init_point}.

    Raises NotFoundError / ForbiddenError / InvalidStateTransitionError.
    """
    orders = db["orders"]
    doc = await orders.find_one({"_id": ObjectId(order_id)})
    if not doc:
        raise NotFoundError("Pedido no encontrado.")
    if doc["user_id"] != user_id:
        raise ForbiddenError("Este pedido no te pertenece.")
    if doc["status"] != OrderStatus.PENDING.value:
        raise InvalidStateTransitionError(
            "Este pedido ya ha sido procesado o cancelado."
        )

    items_mp = [
        {"title": it["name"], "quantity": it["quantity"],
         "unit_price": it["price_at_purchase"], "currency_id": "ARS"}
        for it in doc["items"]
    ]
    front = settings.FRONTEND_URL
    pref_data = {
        "items": items_mp, "external_reference": order_id,
        "back_urls": {
            "success": f"{front}/payment/success?order_id={order_id}",
            "failure": f"{front}/payment/failure?order_id={order_id}",
            "pending": f"{front}/payment/pending?order_id={order_id}",
        },
        "auto_return": "approved",
    }

    try:
        resp = _get_sdk().preference().create(pref_data)
        logger.info("MP response: %s", resp)
        if "response" not in resp:
            msg = resp.get("message", "Error desconocido")
            raise RuntimeError(f"Respuesta inesperada de Mercado Pago: {msg}")
        pref = resp["response"]
        if "id" not in pref or "init_point" not in pref:
            raise RuntimeError(
                "La preferencia de Mercado Pago no contiene los campos necesarios"
            )
        await orders.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"payment_preference_id": pref["id"]}},
        )
        logger.info("Preference %s for order %s.", pref["id"], order_id)
        return {"preference_id": pref["id"], "init_point": pref["init_point"]}
    except (NotFoundError, ForbiddenError, InvalidStateTransitionError):
        raise
    except Exception as exc:
        logger.error("MP preference error: %s", exc, exc_info=True)
        raise RuntimeError(f"Error al comunicarse con Mercado Pago: {exc}") from exc


async def process_webhook(
    db: AsyncIOMotorDatabase,
    topic: Optional[str],
    payment_id: Optional[str],
    x_signature: Optional[str],
    x_request_id: Optional[str],
) -> None:
    """Process a Mercado Pago IPN webhook. Always succeeds (logs errors)."""
    logger.info("Webhook: topic=%s id=%s sig=%s req=%s",
                topic, payment_id, x_signature, x_request_id)

    _validate_signature(payment_id, x_signature, x_request_id)

    if topic != "payment" or not payment_id:
        return

    try:
        pays = db["payments"]
        orders = db["orders"]

        # Idempotency
        if await pays.find_one({"id": int(payment_id)}):
            logger.info("Payment %s already processed.", payment_id)
            return

        info = _get_sdk().payment().get(payment_id)["response"]
        await pays.insert_one(info)
        logger.info("Payment %s saved.", payment_id)

        ref = info.get("external_reference")
        status = info.get("status")
        detail = info.get("status_detail", "N/A")
        pid_str = str(info.get("id", ""))

        if not ref:
            logger.warning("No external_reference in payment %s.", payment_id)
            return

        try:
            oid = ObjectId(ref)
        except Exception:
            logger.warning("Invalid order_id in webhook: %s", ref)
            return

        order = await orders.find_one({"_id": oid})
        if not order:
            logger.warning("Order %s not found.", ref)
            return

        cur = order["status"]
        base = {"payment_id": pid_str, "payment_status": status,
                "payment_status_detail": detail}

        if status == "approved" and cur == OrderStatus.PENDING.value:
            await orders.update_one(
                {"_id": oid},
                {"$set": {**base, "status": OrderStatus.PROCESSING.value}},
            )
            logger.info("Order %s → PROCESSING.", ref)
        elif status in ("rejected", "cancelled"):
            await orders.update_one(
                {"_id": oid},
                {"$set": {**base, "status": OrderStatus.CANCELLED.value}},
            )
            logger.info("Order %s → CANCELLED (%s).", ref, status)
        elif status == "in_process":
            await orders.update_one({"_id": oid}, {"$set": base})
            logger.info("Order %s payment in process.", ref)
        else:
            logger.info("Order %s state '%s' — skip payment '%s'.", ref, cur, status)

    except Exception as exc:
        logger.error("Webhook error: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------


def _validate_signature(
    payment_id: Optional[str],
    x_signature: Optional[str],
    x_request_id: Optional[str],
) -> None:
    """HMAC-SHA256 webhook signature check. Non-blocking (warns only)."""
    secret = settings.MERCADOPAGO_WEBHOOK_SECRET
    if not secret:
        logger.warning("MERCADOPAGO_WEBHOOK_SECRET not configured.")
        return
    if not x_signature:
        logger.info("No x-signature header (normal in MP panel tests).")
        return

    try:
        parts: dict[str, str] = {}
        for item in x_signature.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                parts[k.strip()] = v.strip()
        ts = parts.get("ts")
        rh = parts.get("v1")
        if not ts or not rh:
            logger.warning("x-signature missing ts/v1. Processing anyway.")
            return

        msg = f"id:{payment_id or ''};request-id:{x_request_id or ''};ts:{ts};"
        expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(rh, expected):
            logger.warning("Invalid webhook signature for id=%s.", payment_id)
        else:
            logger.info("Signature OK for id=%s.", payment_id)
    except Exception as exc:
        logger.error("Signature validation error: %s", exc, exc_info=True)
