"""Pricing business logic — dynamic pricing and settings management.

Public API (see design §2.2):
  - get_adjusted_price(db, base_price) -> float
  - is_dynamic_pricing_active(db, current_time=None) -> bool
  - get_pricing_settings(db) -> dict
  - update_pricing_settings(db, settings, admin_user_id) -> dict

All functions receive db: AsyncIOMotorDatabase, raise domain exceptions from
services.exceptions, and return Pydantic models or domain objects.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from models import DynamicPricingSettings
from services.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API — dynamic pricing
# ---------------------------------------------------------------------------


async def get_adjusted_price(
    db: AsyncIOMotorDatabase,
    base_price: float,
) -> float:
    """Apply dynamic pricing multiplier if active. Returns the adjusted price.

    Loads the active pricing settings document from the database and
    applies the multiplier when the current time falls within the
    configured window.
    """
    settings_doc = await db["pricing_settings"].find_one({})
    settings = (
        DynamicPricingSettings(**settings_doc)
        if settings_doc
        else DynamicPricingSettings()
    )

    if _is_active(settings):
        adjusted_price = base_price * settings.multiplier
        return round(adjusted_price, 2)

    return base_price


async def is_dynamic_pricing_active(
    db: AsyncIOMotorDatabase,
    current_time: Optional[datetime] = None,
) -> bool:
    """Check whether dynamic pricing is currently active.

    Reads the pricing settings document and delegates to the time-window
    logic in ``_is_active``.
    """
    settings_doc = await db["pricing_settings"].find_one({})
    settings = (
        DynamicPricingSettings(**settings_doc)
        if settings_doc
        else DynamicPricingSettings()
    )
    return _is_active(settings, current_time)


# ---------------------------------------------------------------------------
# Public API — settings (admin)
# ---------------------------------------------------------------------------


async def get_pricing_settings(
    db: AsyncIOMotorDatabase,
) -> DynamicPricingSettings:
    """Return the active pricing settings document, or defaults if none exist."""
    settings_doc = await db["pricing_settings"].find_one({})
    if settings_doc:
        return DynamicPricingSettings(**settings_doc)
    return DynamicPricingSettings()


async def update_pricing_settings(
    db: AsyncIOMotorDatabase,
    update: DynamicPricingSettings,  # accepts a DynamicPricingSettings model
    admin_user_id: str,
) -> DynamicPricingSettings:
    """Create or update the pricing settings document.

    Raises:
        ValidationError: when the input is invalid.
    """
    # Basic validation
    if update.multiplier <= 0:
        raise ValidationError("El multiplicador debe ser mayor a cero.")

    existing = await db["pricing_settings"].find_one({})

    update_data = {
        "enabled": update.enabled,
        "multiplier": update.multiplier,
        "start_day": update.start_day,
        "end_day": update.end_day,
        "start_hour": update.start_hour,
        "end_hour": update.end_hour,
        "updated_at": datetime.now(tz=timezone.utc),
        "updated_by": admin_user_id,
    }

    if existing:
        await db["pricing_settings"].update_one(
            {"_id": existing["_id"]},
            {"$set": update_data},
        )
        updated = await db["pricing_settings"].find_one({"_id": existing["_id"]})
        logger.info(
            "Admin %s updated pricing settings.",
            admin_user_id,
        )
        return DynamicPricingSettings(**updated)
    else:
        new_settings = DynamicPricingSettings(**update_data)
        result = await db["pricing_settings"].insert_one(
            new_settings.model_dump(exclude={"id"}, by_alias=False)
        )
        created = await db["pricing_settings"].find_one({"_id": result.inserted_id})
        logger.info(
            "Admin %s created pricing settings.",
            admin_user_id,
        )
        return DynamicPricingSettings(**created)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _is_active(
    settings: DynamicPricingSettings,
    current_time: Optional[datetime] = None,
) -> bool:
    """Check whether the current time falls within the dynamic pricing window.

    Logic copied verbatim from ``pricing_helpers.is_dynamic_pricing_active``.
    """
    if not settings.enabled:
        return False

    if current_time is None:
        current_time = datetime.now(tz=timezone.utc)

    # Obtener día (1=Lunes, 7=Domingo) y hora (0-23)
    current_day = current_time.weekday() + 1
    current_hour = current_time.hour

    # Lógica de rango de días
    # Si el día actual está fuera del rango [start_day, end_day]
    # Nota: Esto no maneja rangos que cruzan el lunes (ej: Domingo a Martes),
    # pero para "Viernes a Domingo" funciona perfecto.
    if not (settings.start_day <= current_day <= settings.end_day):
        return False

    # Lógica de horas
    if settings.start_hour == settings.end_hour:
        # Si las horas son iguales, se considera activo todo el día en el rango de días
        return True

    if settings.start_hour < settings.end_hour:
        # Rango normal (ej: 08:00 a 20:00)
        return settings.start_hour <= current_hour < settings.end_hour
    else:
        # Rango nocturno (ej: 20:00 a 06:00)
        # Activo si es tarde en la noche O temprano en la mañana
        return current_hour >= settings.start_hour or current_hour < settings.end_hour
