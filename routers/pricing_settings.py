from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from datetime import datetime, timezone
import logging

from models import DynamicPricingSettings, DynamicPricingUpdate, TokenData
from database import get_database, get_collection
from security import get_current_admin_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Colección de MongoDB
def get_pricing_settings_collection(db=Depends(get_database)):
    return get_collection("pricing_settings")


@router.get("/pricing-settings", response_model=DynamicPricingSettings)
async def get_pricing_settings_public(
    pricing_settings_collection = Depends(get_pricing_settings_collection)
):
    """
    Obtiene la configuración actual de precios dinámicos (público).
    """
    try:
        settings = await pricing_settings_collection.find_one({})
        
        if not settings:
            # Si no existe configuración, devolver valores por defecto
            return DynamicPricingSettings(
                enabled=False,
                multiplier=1.0,
                start_day=5,
                end_day=7,
                start_hour=20,
                end_hour=6,
                updated_at=datetime.now(tz=timezone.utc)
            )
        
        return DynamicPricingSettings(**settings)
    
    except Exception as e:
        logger.error(f"Error al obtener configuración de precios: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener configuración de precios."
        )


@router.get("/admin/pricing-settings", response_model=DynamicPricingSettings, tags=["Admin"])
async def get_pricing_settings_admin(
    pricing_settings_collection = Depends(get_pricing_settings_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Obtiene la configuración actual de precios.
    """
    try:
        settings = await pricing_settings_collection.find_one({})
        
        if not settings:
            # Devolver valores por defecto si no existe
            return DynamicPricingSettings(
                enabled=False,
                multiplier=1.0,
                start_day=5,
                end_day=7,
                start_hour=20,
                end_hour=6,
                updated_at=datetime.now(tz=timezone.utc)
            )
        
        return DynamicPricingSettings(**settings)
    
    except Exception as e:
        logger.error(f"Error al obtener configuración de precios: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener configuración de precios."
        )


@router.put("/admin/pricing-settings", response_model=DynamicPricingSettings, tags=["Admin"])
async def update_pricing_settings(
    settings_update: DynamicPricingUpdate,
    pricing_settings_collection = Depends(get_pricing_settings_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Actualiza la configuración de precios dinámicos.
    """
    try:
        existing_settings = await pricing_settings_collection.find_one({})
        
        update_data = {
            "enabled": settings_update.enabled,
            "multiplier": settings_update.multiplier,
            "start_day": settings_update.start_day,
            "end_day": settings_update.end_day,
            "start_hour": settings_update.start_hour,
            "end_hour": settings_update.end_hour,
            "updated_at": datetime.now(tz=timezone.utc),
            "updated_by": current_admin_user.user_id
        }
        
        if existing_settings:
            await pricing_settings_collection.update_one(
                {"_id": existing_settings["_id"]},
                {"$set": update_data}
            )
            updated_settings = await pricing_settings_collection.find_one({"_id": existing_settings["_id"]})
            logger.info(f"Admin {current_admin_user.username} actualizó la configuración de precios dinámicos.")
            return DynamicPricingSettings(**updated_settings)
        else:
            new_settings = DynamicPricingSettings(**update_data)
            settings_dict = new_settings.model_dump(exclude={"id"}, by_alias=False)
            result = await pricing_settings_collection.insert_one(settings_dict)
            created_settings = await pricing_settings_collection.find_one({"_id": result.inserted_id})
            logger.info(f"Admin {current_admin_user.username} creó la configuración de precios dinámicos.")
            return DynamicPricingSettings(**created_settings)
    
    except Exception as e:
        logger.error(f"Error al actualizar configuración de precios: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar configuración de precios."
        )
