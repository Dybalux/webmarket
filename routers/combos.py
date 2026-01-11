from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime

from models import Combo, ComboCreate, ComboUpdate, TokenData
from database import get_collection
from security import get_current_admin_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Endpoint Público ---

@router.get("/", response_model=List[Combo])
async def get_active_combos():
    """
    Obtiene todos los combos activos disponibles para compra.
    Endpoint público - no requiere autenticación.
    """
    try:
        combos_collection = get_collection("combos")
        combos_cursor = combos_collection.find({"active": True}).sort("created_at", -1)
        combos_list = []
        
        async for combo_doc in combos_cursor:
            combos_list.append(Combo(**combo_doc))
        
        logger.info(f"Se obtuvieron {len(combos_list)} combos activos.")
        return combos_list
    
    except Exception as e:
        logger.error(f"Error al obtener combos: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener los combos."
        )


@router.get("/{combo_id}", response_model=Combo)
async def get_combo_by_id(combo_id: str):
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
        combos_collection = get_collection("combos")
        combo = await combos_collection.find_one({"_id": ObjectId(combo_id), "active": True})
        
        if not combo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Combo no encontrado."
            )
        
        return Combo(**combo)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al obtener combo {combo_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener el combo."
        )


# --- Endpoints de Administrador ---

@router.get("/admin/all", response_model=List[Combo], tags=["Admin"])
async def get_all_combos_admin(
    current_admin_user: TokenData = Depends(get_current_admin_user),
    include_inactive: bool = Query(False, description="Incluir combos inactivos")
):
    """
    [Admin] Obtiene todos los combos (activos e inactivos).
    Requiere permisos de administrador.
    """
    try:
        combos_collection = get_collection("combos")
        
        query = {} if include_inactive else {"active": True}
        combos_cursor = combos_collection.find(query).sort("created_at", -1)
        combos_list = []
        
        async for combo_doc in combos_cursor:
            combos_list.append(Combo(**combo_doc))
        
        logger.info(f"Admin {current_admin_user.username} obtuvo {len(combos_list)} combos.")
        return combos_list
    
    except Exception as e:
        logger.error(f"Error al obtener combos (admin): {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener los combos."
        )


@router.post("/admin", response_model=Combo, status_code=status.HTTP_201_CREATED, tags=["Admin"])
async def create_combo(
    combo_data: ComboCreate,
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Crea un nuevo combo de productos.
    Requiere permisos de administrador.
    """
    try:
        # Validar que los productos existen
        products_collection = get_collection("products")
        for item in combo_data.items:
            if not ObjectId.is_valid(item.product_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"ID de producto inválido: {item.product_id}"
                )
            
            product = await products_collection.find_one({"_id": ObjectId(item.product_id)})
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Producto con ID {item.product_id} no encontrado."
                )
        
        # Crear el combo
        combos_collection = get_collection("combos")
        new_combo = Combo(**combo_data.model_dump())
        combo_dict = new_combo.model_dump(exclude={"_id"}, by_alias=False)
        
        result = await combos_collection.insert_one(combo_dict)
        
        if not result.inserted_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No se pudo crear el combo."
            )
        
        created_combo = await combos_collection.find_one({"_id": result.inserted_id})
        logger.info(f"Admin {current_admin_user.username} creó el combo '{combo_data.name}' (ID: {result.inserted_id}).")
        
        return Combo(**created_combo)
    
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
        combos_collection = get_collection("combos")
        combo = await combos_collection.find_one({"_id": ObjectId(combo_id)})
        
        if not combo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Combo no encontrado."
            )
        
        # Validar productos si se están actualizando
        if combo_data.items:
            products_collection = get_collection("products")
            for item in combo_data.items:
                if not ObjectId.is_valid(item.product_id):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"ID de producto inválido: {item.product_id}"
                    )
                
                product = await products_collection.find_one({"_id": ObjectId(item.product_id)})
                if not product:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Producto con ID {item.product_id} no encontrado."
                    )
        
        # Actualizar solo los campos proporcionados
        update_data = combo_data.model_dump(exclude_unset=True)
        update_data["updated_at"] = datetime.utcnow()
        
        await combos_collection.update_one(
            {"_id": ObjectId(combo_id)},
            {"$set": update_data}
        )
        
        updated_combo = await combos_collection.find_one({"_id": ObjectId(combo_id)})
        logger.info(f"Admin {current_admin_user.username} actualizó el combo {combo_id}.")
        
        return Combo(**updated_combo)
    
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
        combos_collection = get_collection("combos")
        combo = await combos_collection.find_one({"_id": ObjectId(combo_id)})
        
        if not combo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Combo no encontrado."
            )
        
        if permanent:
            # Eliminación permanente
            await combos_collection.delete_one({"_id": ObjectId(combo_id)})
            logger.info(f"Admin {current_admin_user.username} eliminó permanentemente el combo {combo_id}.")
            return {"message": "Combo eliminado permanentemente."}
        else:
            # Soft delete - solo desactivar
            await combos_collection.update_one(
                {"_id": ObjectId(combo_id)},
                {"$set": {"active": False, "updated_at": datetime.utcnow()}}
            )
            logger.info(f"Admin {current_admin_user.username} desactivó el combo {combo_id}.")
            return {"message": "Combo desactivado correctamente."}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al eliminar combo: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al eliminar el combo."
        )
