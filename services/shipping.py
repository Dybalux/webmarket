"""Shipping business logic — zones, prices, and cost calculation.

Public API (see design §2.7):
  - get_shipping_prices(db) -> dict
  - calculate_shipping_cost(db, zone, total_items, has_combo) -> float

All functions receive db: AsyncIOMotorDatabase and return domain dicts or scalars.
"""

from __future__ import annotations

import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default prices (returned when no settings document exists or on error)
# ---------------------------------------------------------------------------

_DEFAULT_PRICES: dict = {
    "central": {
        "price": 0.0,
        "description": "🎁 ENVÍO GRATIS - Zona Céntrica de Santa María",
        "enabled": True,
    },
    "remote": {
        "price": 1000.0,
        "description": "🚛 Envío a Zonas Alejadas",
        "enabled": True,
    },
    "pickup": {
        "price": 0.0,
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
            "price": settings.get("central_zone_price", 0.0),
            "description": settings.get(
                "central_zone_description",
                _DEFAULT_PRICES["central"]["description"],
            ),
            "enabled": True,
        }

    # Remote zone
    if settings.get("remote_zone_enabled", True):
        response["remote"] = {
            "price": settings.get("remote_zone_price", 1000.0),
            "description": settings.get(
                "remote_zone_description",
                _DEFAULT_PRICES["remote"]["description"],
            ),
            "enabled": True,
        }

    # Pickup
    if settings.get("pickup_enabled", True):
        response["pickup"] = {
            "price": settings.get("pickup_price", 0.0),
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
) -> float:
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
            return 0.0

        settings = await db["shipping_settings"].find_one({})
        return float(settings.get("central_zone_price", 0.0)) if settings else 0.0

    if zone == "remote":
        settings = await db["shipping_settings"].find_one({})
        return float(settings.get("remote_zone_price", 1000.0)) if settings else 1000.0

    # pickup — always free
    return 0.0
