from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List
from bson import ObjectId

from motor.motor_asyncio import AsyncIOMotorDatabase

from models import Combo, ComboCreate, ComboUpdate, ComboDetailed, TokenData
from database import get_database
from security import get_current_admin_user
from services.combos import (
    list_active_combos,
    get_combo_by_id as _svc_get_combo_by_id,
    list_all_combos,
    create_combo as _svc_create_combo,
    update_combo as _svc_update_combo,
    delete_combo as _svc_delete_combo,
)
from services.exceptions import InternalError, NotFoundError, ValidationError

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Endpoint Público ---

@router.get("/", response_model=List[ComboDetailed])
async def get_active_combos(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Obtiene todos los combos activos con información detallada de productos.
    Incluye nombre, precio, imagen y stock de cada producto en el combo.
    Optimizado con bulk queries para mejor performance.
    Endpoint público - no requiere autenticación.
    """
    try:
        return await list_active_combos(db)
    except Exception as e:
        logger.error(f"Error al obtener combos: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener los combos."
        )



@router.get("/{combo_id}", response_model=Combo)
async def get_combo_by_id(
    combo_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Obtiene un combo específico por su ID.
    Endpoint público - no requiere autenticación.
    """
    if not ObjectId.is_valid(combo_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de combo inválido."
        )
    
    try:
        return await _svc_get_combo_by_id(db, combo_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Combo no encontrado."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al obtener combo {combo_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener el combo."
        )


# --- Endpoints de Administrador ---

@router.get("/admin/all", response_model=List[ComboDetailed], tags=["Admin"])
async def get_all_combos_admin(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
    include_inactive: bool = Query(False, description="Incluir combos inactivos")
):
    """
    [Admin] Obtiene todos los combos (activos e inactivos) con información detallada.
    Incluye nombres de productos, cálculo de costos y ahorros.
    """
    try:
        return await list_all_combos(db, include_inactive)
    except Exception as e:
        logger.error(f"Error al obtener combos admin: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener la lista de combos."
        )


@router.post("/admin", response_model=Combo, status_code=status.HTTP_201_CREATED, tags=["Admin"])
async def create_combo(
    combo_data: ComboCreate,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Crea un nuevo combo de productos.
    Requiere permisos de administrador.
    """
    try:
        return await _svc_create_combo(db, combo_data, current_admin_user.user_id)
    except ValidationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except InternalError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al crear combo: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al crear el combo."
        )


@router.put("/admin/{combo_id}", response_model=Combo, tags=["Admin"])
async def update_combo(
    combo_id: str,
    combo_data: ComboUpdate,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Actualiza un combo existente.
    Requiere permisos de administrador.
    """
    if not ObjectId.is_valid(combo_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de combo inválido."
        )
    
    try:
        return await _svc_update_combo(db, combo_id, combo_data, current_admin_user.user_id)
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except ValidationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al actualizar combo: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar el combo."
        )


@router.delete("/admin/{combo_id}", tags=["Admin"])
async def delete_combo(
    combo_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    permanent: bool = Query(False, description="Eliminar permanentemente (true) o solo desactivar (false)"),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Elimina o desactiva un combo.
    Por defecto solo desactiva (soft delete). Usar permanent=true para eliminar completamente.
    Requiere permisos de administrador.
    """
    if not ObjectId.is_valid(combo_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de combo inválido."
        )
    
    try:
        return await _svc_delete_combo(db, combo_id, permanent, current_admin_user.user_id)
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al eliminar combo: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al eliminar el combo."
        )
