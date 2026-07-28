"""Shipping business logic — zones, prices, and cost calculation.

Public API (see design §2.7):
  - get_shipping_prices(db) -> dict
  - calculate_shipping_cost(db, zone, total_items, has_combo) -> Decimal

All functions receive db: AsyncIOMotorDatabase and return domain dicts or scalars.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from utils.money import from_decimal128

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default prices (returned when no settings document exists or on error)
# ---------------------------------------------------------------------------

_DEFAULT_PRICES: dict = {
    "central": {
        "price": Decimal("0.00"),
        "description": "🎁 ENVÍO GRATIS - Zona Céntrica de Santa María",
        "enabled": True,
    },
    "remote": {
        "price": Decimal("1000.00"),
        "description": "🚛 Envío a Zonas Alejadas",
        "enabled": True,
    },
    "pickup": {
        "price": Decimal("0.00"),
        "description": "🏪 Retiro en Persona - GRATIS",
        "address": "Configurar dirección en panel de administración",
        "enabled": True,
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_shipping_prices(
    db: AsyncIOMotorDatabase,
) -> dict:
    """Return the enabled shipping zones and their prices.

    Reads the ``shipping_settings`` collection. When no settings document
    exists, returns built-in defaults.
    """
    try:
        settings = await db["shipping_settings"].find_one({})
    except Exception:
        logger.exception("Error reading shipping settings, returning defaults.")
        return dict(_DEFAULT_PRICES)

    if not settings:
        return dict(_DEFAULT_PRICES)

    response: dict = {}

    # Central zone
    if settings.get("central_zone_enabled", True):
        response["central"] = {
            "price": from_decimal128(settings.get("central_zone_price", Decimal("0.00"))),
            "description": settings.get(
                "central_zone_description",
                _DEFAULT_PRICES["central"]["description"],
            ),
            "enabled": True,
        }

    # Remote zone
    if settings.get("remote_zone_enabled", True):
        response["remote"] = {
            "price": from_decimal128(settings.get("remote_zone_price", Decimal("1000.00"))),
            "description": settings.get(
                "remote_zone_description",
                _DEFAULT_PRICES["remote"]["description"],
            ),
            "enabled": True,
        }

    # Pickup
    if settings.get("pickup_enabled", True):
        response["pickup"] = {
            "price": from_decimal128(settings.get("pickup_price", Decimal("0.00"))),
            "description": settings.get(
                "pickup_description",
                _DEFAULT_PRICES["pickup"]["description"],
            ),
            "address": settings.get(
                "pickup_address",
                _DEFAULT_PRICES["pickup"]["address"],
            ),
            "enabled": True,
        }

    return response


async def calculate_shipping_cost(
    db: AsyncIOMotorDatabase,
    zone: str,
    total_items: int,
    has_combo: bool,
) -> Decimal:
    """Compute the shipping cost for an order based on zone and cart contents.

    * ``central``: free when *total_items >= 2* or *has_combo* is True.
    * ``remote``: always charges the configured remote price.
    * ``pickup``: always free.
    """
    if zone == "central":
        if total_items >= 2 or has_combo:
            logger.info(
                "Free shipping for central zone (items=%s, combo=%s).",
                total_items,
                has_combo,
            )
            return Decimal("0.00")

        settings = await db["shipping_settings"].find_one({})
        return from_decimal128(
            settings.get("central_zone_price", Decimal("0.00"))
        ) if settings else Decimal("0.00")

    if zone == "remote":
        settings = await db["shipping_settings"].find_one({})
        return from_decimal128(
            settings.get("remote_zone_price", Decimal("1000.00"))
        ) if settings else Decimal("1000.00")

    # pickup — always free
    return Decimal("0.00")
