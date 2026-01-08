from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from datetime import datetime
import logging

from models import PaymentSettings, PaymentSettingsUpdate, TokenData
from database import get_database, get_collection
from security import get_current_admin_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Colección de MongoDB
def get_payment_settings_collection(db=Depends(get_database)):
    return get_collection("payment_settings")


@router.get("/payment-settings", response_model=PaymentSettings)
async def get_payment_settings_public(
    payment_settings_collection = Depends(get_payment_settings_collection)
):
    """
    Obtiene la configuración actual de pagos (público).
    Endpoint para que el frontend obtenga el alias y WhatsApp para transferencias.
    """
    try:
        settings = await payment_settings_collection.find_one({})
        
        if not settings:
            # Si no existe configuración, devolver valores por defecto
            logger.warning("No se encontró configuración de pagos. Devolviendo valores por defecto.")
            return PaymentSettings(
                transfer_alias="ESCABI.API.MP",
                transfer_whatsapp="+5491112345678",
                updated_at=datetime.utcnow()
            )
        
        return PaymentSettings(**settings)
    
    except Exception as e:
        logger.error(f"Error al obtener configuración de pagos: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener configuración de pagos."
        )


@router.get("/admin/payment-settings", response_model=PaymentSettings, tags=["Admin"])
async def get_payment_settings_admin(
    payment_settings_collection = Depends(get_payment_settings_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Obtiene la configuración actual de pagos.
    Requiere permisos de administrador.
    """
    try:
        settings = await payment_settings_collection.find_one({})
        
        if not settings:
            logger.warning("No se encontró configuración de pagos.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró configuración de pagos. Ejecuta el script de inicialización."
            )
        
        logger.info(f"Admin {current_admin_user.username} consultó la configuración de pagos.")
        return PaymentSettings(**settings)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al obtener configuración de pagos: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener configuración de pagos."
        )


@router.put("/admin/payment-settings", response_model=PaymentSettings, tags=["Admin"])
async def update_payment_settings(
    settings_update: PaymentSettingsUpdate,
    payment_settings_collection = Depends(get_payment_settings_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Actualiza la configuración de pagos (alias y WhatsApp).
    Requiere permisos de administrador.
    """
    try:
        # Verificar si existe configuración
        existing_settings = await payment_settings_collection.find_one({})
        
        update_data = {
            "transfer_alias": settings_update.transfer_alias,
            "transfer_whatsapp": settings_update.transfer_whatsapp,
            "updated_at": datetime.utcnow(),
            "updated_by": current_admin_user.user_id
        }
        
        if existing_settings:
            # Actualizar configuración existente
            await payment_settings_collection.update_one(
                {"_id": existing_settings["_id"]},
                {"$set": update_data}
            )
            logger.info(
                f"Admin {current_admin_user.username} actualizó la configuración de pagos. "
                f"Alias: {settings_update.transfer_alias}, WhatsApp: {settings_update.transfer_whatsapp}"
            )
            
            # Obtener configuración actualizada
            updated_settings = await payment_settings_collection.find_one({"_id": existing_settings["_id"]})
            return PaymentSettings(**updated_settings)
        else:
            # Crear nueva configuración
            new_settings = PaymentSettings(**update_data)
            settings_dict = new_settings.model_dump(exclude={"id"}, by_alias=False)
            result = await payment_settings_collection.insert_one(settings_dict)
            
            logger.info(
                f"Admin {current_admin_user.username} creó la configuración de pagos. "
                f"Alias: {settings_update.transfer_alias}, WhatsApp: {settings_update.transfer_whatsapp}"
            )
            
            # Obtener configuración creada
            created_settings = await payment_settings_collection.find_one({"_id": result.inserted_id})
            return PaymentSettings(**created_settings)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al actualizar configuración de pagos: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar configuración de pagos."
        )
