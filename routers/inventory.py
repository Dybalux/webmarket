from fastapi import APIRouter, Depends, HTTPException, status, Body
from typing import List
from bson import ObjectId
from datetime import datetime

from models import Product, InventoryAlert, TokenData
from database import get_database, get_collection
from security import get_current_admin_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Umbral para generar alertas de bajo inventario
LOW_STOCK_THRESHOLD = 10

# Colecciones de MongoDB
def get_products_collection(db=Depends(get_database)):
    return get_collection("products")
def get_alerts_collection(db=Depends(get_database)):
    return get_collection("inventory_alerts")


async def check_and_create_alert(products_collection, alerts_collection, product_id: str):
    """
    Verifica el stock de un producto y crea una alerta si es bajo.
    """
    product = await products_collection.find_one({"_id": ObjectId(product_id)})
    if product and product.get("stock", 0) <= LOW_STOCK_THRESHOLD:
        alert_message = f"El stock del producto '{product['name']}' es bajo ({product['stock']})."
        
        # Opcional: Evitar duplicar alertas si ya existe una reciente
        existing_alert = await alerts_collection.find_one({
            "product_id": product_id,
            "message": alert_message
        })
        if not existing_alert:
            alert = InventoryAlert(
                _id = None,
                product_id=product_id,
                product_name=product["name"],
                current_stock=product["stock"],
                threshold=LOW_STOCK_THRESHOLD,
                message=alert_message
            )
            await alerts_collection.insert_one(alert.model_dump())
            logger.warning(f"ALERTA DE INVENTARIO: {alert_message}")

# --- Endpoints de Inventario (Solo Admin) ---

@router.put("/{product_id}/stock", response_model=Product)
async def update_product_stock(
    product_id: str,
    new_stock: int = Body(..., embed=True, ge=0), # Recibe un JSON como {"new_stock": 50}
    products_collection = Depends(get_products_collection),
    alerts_collection = Depends(get_alerts_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Establece manualmente el stock de un producto específico.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    result = await products_collection.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"stock": new_stock}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")

    # Verificar si se debe generar una alerta después de la actualización
    await check_and_create_alert(products_collection, alerts_collection, product_id)
    
    updated_product = await products_collection.find_one({"_id": ObjectId(product_id)})
    logger.info(f"Admin {current_admin_user.username} actualizó el stock del producto {product_id} a {new_stock}.")
    return Product(**updated_product)

@router.put("/{product_id}/stock/add", response_model=Product)
async def add_to_product_stock(
    product_id: str,
    quantity_to_add: int = Body(..., embed=True, gt=0), # Recibe {"quantity_to_add": 10}
    products_collection = Depends(get_products_collection),
    alerts_collection = Depends(get_alerts_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Añade una cantidad al stock de un producto (reposición).
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    result = await products_collection.update_one(
        {"_id": ObjectId(product_id)},
        {"$inc": {"stock": quantity_to_add}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")
    
    # Verificar si se debe generar una alerta
    await check_and_create_alert(products_collection, alerts_collection, product_id)
    
    updated_product = await products_collection.find_one({"_id": ObjectId(product_id)})
    logger.info(f"Admin {current_admin_user.username} añadió {quantity_to_add} unidades al stock del producto {product_id}.")
    return Product(**updated_product)

@router.get("/alerts", response_model=List[InventoryAlert])
async def get_inventory_alerts(
    limit: int = 100,
    alerts_collection = Depends(get_alerts_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Obtiene las últimas alertas de bajo inventario.
    Limitado por defecto a 100 resultados para evitar sobrecarga.
    """
    alerts_cursor = alerts_collection.find().sort("timestamp", -1).limit(limit)
    return [InventoryAlert(**alert) async for alert in alerts_cursor]