from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime

from models import Combo, ComboCreate, ComboUpdate, ComboDetailed, ComboItemDetailed, TokenData, DynamicPricingSettings
from database import get_collection
from security import get_current_admin_user
from pricing_helpers import get_adjusted_price
from routers.pricing_settings import get_pricing_settings_collection

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Endpoint Público ---

@router.get("/", response_model=List[ComboDetailed])
async def get_active_combos():
    """
    Obtiene todos los combos activos con información detallada de productos.
    Incluye nombre, precio, imagen y stock de cada producto en el combo.
    Optimizado con bulk queries para mejor performance.
    Endpoint público - no requiere autenticación.
    """
    try:
        combos_collection = get_collection("combos")
        products_collection = get_collection("products")
        
        # Obtener todos los combos activos
        combos_cursor = combos_collection.find({"active": True}).sort("created_at", -1)
        combos_list = []
        
        async for combo_doc in combos_cursor:
            combos_list.append(combo_doc)
        
        # Obtener configuración de precios dinámicos
        pricing_settings_collection = get_collection("pricing_settings")
        pricing_doc = await pricing_settings_collection.find_one({})
        pricing_settings = DynamicPricingSettings(**pricing_doc) if pricing_doc else DynamicPricingSettings()

        if not combos_list:
            return []
        
        # OPTIMIZACIÓN: Obtener todos los product_ids de todos los combos
        all_product_ids = set()
        for combo in combos_list:
            for item in combo.get("items", []):
                all_product_ids.add(ObjectId(item["product_id"]))
        
        # Bulk query para obtener todos los productos de una vez
        products_cursor = products_collection.find(
            {"_id": {"$in": list(all_product_ids)}},
            {"name": 1, "price": 1, "image_url": 1, "stock": 1}
        )
        products_dict = {str(p["_id"]): p async for p in products_cursor}
        
        # Construir respuesta enriquecida
        enriched_combos = []
        
        for combo in combos_list:
            # Enriquecer items del combo con información de productos
            enriched_items = []
            
            for item in combo.get("items", []):
                product_id = item["product_id"]
                
                if product_id in products_dict:
                    product = products_dict[product_id]
                    enriched_item = ComboItemDetailed(
                        product_id=product_id,
                        quantity=item["quantity"],
                        name=product["name"],
                        price=product["price"],
                        image_url=product.get("image_url"),
                        stock=product.get("stock", 0)
                    )
                    enriched_items.append(enriched_item)
                else:
                    # Producto no encontrado - skip
                    logger.warning(f"Producto {product_id} del combo {combo['_id']} no encontrado")
            
            # Calcular el costo total de los productos individuales
            total_items_cost = sum(item.price * item.quantity for item in enriched_items)
            combo_price = get_adjusted_price(combo["price"], pricing_settings)
            savings = round(total_items_cost - combo_price, 2)
            
            # Crear combo enriquecido
            enriched_combo = ComboDetailed(
                _id=combo["_id"],
                name=combo["name"],
                description=combo.get("description"),
                price=combo_price,
                image_url=combo.get("image_url"),

                items=enriched_items,
                active=combo.get("active", True),
                created_at=combo.get("created_at"),
                updated_at=combo.get("updated_at"),
                total_items_cost=round(total_items_cost, 2),
                savings=savings
            )
            enriched_combos.append(enriched_combo)
        
        logger.info(f"Se obtuvieron {len(enriched_combos)} combos activos con información detallada.")
        return enriched_combos
    
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
        
        combo_obj = Combo(**combo)
        # Obtener configuración de precios dinámicos
        pricing_settings_collection = get_collection("pricing_settings")
        pricing_doc = await pricing_settings_collection.find_one({})
        pricing_settings = DynamicPricingSettings(**pricing_doc) if pricing_doc else DynamicPricingSettings()
        
        # Aplicar precio dinámico
        combo_obj.price = get_adjusted_price(combo_obj.price, pricing_settings)
        return combo_obj

    
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
    current_admin_user: TokenData = Depends(get_current_admin_user),
    include_inactive: bool = Query(False, description="Incluir combos inactivos")
):
    """
    [Admin] Obtiene todos los combos (activos e inactivos) con información detallada.
    Incluye nombres de productos, cálculo de costos y ahorros.
    """
    try:
        combos_collection = get_collection("combos")
        products_collection = get_collection("products")
        
        query = {} if include_inactive else {"active": True}
        combos_cursor = combos_collection.find(query).sort("created_at", -1)
        
        combos_list = []
        async for combo in combos_cursor:
            combos_list.append(combo)
            
        if not combos_list:
            return []

        # 1. Obtener todos los IDs de productos requeridos para hacer una sola consulta (Optimización)
        all_product_ids = set()
        for combo in combos_list:
            for item in combo.get("items", []):
                # Asegurar que sea ObjectId
                try:
                    pid = item["product_id"]
                    if isinstance(pid, str):
                        all_product_ids.add(ObjectId(pid))
                    else:
                        all_product_ids.add(pid)
                except:
                    continue
        
        # 2. Buscar productos en DB
        products_cursor = products_collection.find(
            {"_id": {"$in": list(all_product_ids)}},
            {"name": 1, "price": 1, "image_url": 1, "stock": 1}
        )
        products_dict = {str(p["_id"]): p async for p in products_cursor}
        
        # 3. Construir respuesta enriquecida
        enriched_combos = []
        
        for combo in combos_list:
            enriched_items = []
            
            # Enriquecer items
            for item in combo.get("items", []):
                pid_str = str(item["product_id"])
                
                if pid_str in products_dict:
                    prod_data = products_dict[pid_str]
                    enriched_items.append(ComboItemDetailed(
                        product_id=pid_str,
                        quantity=item["quantity"],
                        name=prod_data.get("name", "Producto Desconocido"),
                        price=prod_data.get("price", 0.0),
                        image_url=prod_data.get("image_url"),
                        stock=prod_data.get("stock", 0)
                    ))
            
            # Calcular totales (Usamos el precio base del combo para Admin, sin precios dinámicos temporales)
            total_items_cost = sum(item.price * item.quantity for item in enriched_items)
            combo_base_price = combo["price"]
            savings = round(total_items_cost - combo_base_price, 2)
            
            enriched_combos.append(ComboDetailed(
                _id=combo["_id"],
                name=combo["name"],
                description=combo.get("description"),
                price=combo_base_price,
                image_url=combo.get("image_url"),
                items=enriched_items,
                active=combo.get("active", True),
                created_at=combo.get("created_at"),
                updated_at=combo.get("updated_at"),
                total_items_cost=round(total_items_cost, 2),
                savings=savings
            ))
            
        logger.info(f"Admin {current_admin_user.username} consultó combos detallados.")
        return enriched_combos
    
    except Exception as e:
        logger.error(f"Error al obtener combos admin: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener la lista de combos."
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
