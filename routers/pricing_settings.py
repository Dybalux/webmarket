from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, timezone
import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

from models import DynamicPricingSettings, DynamicPricingUpdate, TokenData
from database import get_database
from security import get_current_admin_user
from services import pricing as pricing_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /pricing-settings — public
# ---------------------------------------------------------------------------


@router.get("/pricing-settings", response_model=DynamicPricingSettings)
async def get_pricing_settings_public(
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Obtiene la configuración actual de precios dinámicos (público).
    """
    try:
        return await pricing_service.get_pricing_settings(db)
    except Exception as e:
        logger.error(f"Error al obtener configuración de precios: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener configuración de precios.",
        )


# ---------------------------------------------------------------------------
# GET /admin/pricing-settings — admin
# ---------------------------------------------------------------------------


@router.get("/admin/pricing-settings", response_model=DynamicPricingSettings, tags=["Admin"])
async def get_pricing_settings_admin(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """
    [Admin] Obtiene la configuración actual de precios.
    """
    try:
        return await pricing_service.get_pricing_settings(db)
    except Exception as e:
        logger.error(f"Error al obtener configuración de precios: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener configuración de precios.",
        )


# ---------------------------------------------------------------------------
# PUT /admin/pricing-settings — admin (update)
# ---------------------------------------------------------------------------


@router.put("/admin/pricing-settings", response_model=DynamicPricingSettings, tags=["Admin"])
async def update_pricing_settings(
    settings_update: DynamicPricingUpdate,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """
    [Admin] Actualiza la configuración de precios dinámicos.
    """
    try:
        settings = DynamicPricingSettings(
            enabled=settings_update.enabled,
            multiplier=settings_update.multiplier,
            start_day=settings_update.start_day,
            end_day=settings_update.end_day,
            start_hour=settings_update.start_hour,
            end_hour=settings_update.end_hour,
        )
        return await pricing_service.update_pricing_settings(
            db, settings, current_admin_user.user_id
        )
    except Exception as e:
        logger.error(f"Error al actualizar configuración de precios: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar configuración de precios.",
        )
