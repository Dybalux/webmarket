"""
Helpers para validación de stock con transacciones atómicas de MongoDB.
Previene race conditions y overselling.
"""

from typing import List, Dict
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorClientSession
from fastapi import HTTPException, status
import logging

logger = logging.getLogger(__name__)

async def validate_and_reserve_stock(
    session: AsyncIOMotorClientSession,
    products_collection,
    items: List[Dict[str, any]]
) -> List[Dict]:
    """
    Valida y reserva stock para una lista de productos de forma atómica.
    
    Args:
        session: Sesión de transacción de MongoDB
        products_collection: Colección de productos
        items: Lista de items con product_id y quantity
        
    Returns:
        Lista de productos validados con información completa
        
    Raises:
        HTTPException: Si algún producto no existe o no tiene stock suficiente
    """
    validated_products = []
    
    for item in items:
        product_id = item.get("product_id")
        quantity = item.get("quantity")
        
        if not ObjectId.is_valid(product_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ID de producto inválido: {product_id}"
            )
        
        # Buscar el producto dentro de la transacción
        product = await products_collection.find_one(
            {"_id": ObjectId(product_id)},
            session=session
        )
        
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto no encontrado: {product_id}"
            )
        
        # Verificar stock disponible
        current_stock = product.get("stock", 0)
        if current_stock < quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stock insuficiente para '{product['name']}'. Disponible: {current_stock}, solicitado: {quantity}"
            )
        
        validated_products.append({
            "product_id": str(product["_id"]),
            "name": product["name"],
            "price": product["price"],
            "quantity": quantity,
            "current_stock": current_stock
        })
    
    return validated_products

async def update_stock_atomic(
    session: AsyncIOMotorClientSession,
    products_collection,
    items: List[Dict[str, any]]
) -> None:
    """
    Actualiza el stock de productos de forma atómica.
    Debe llamarse dentro de una transacción.
    
    Args:
        session: Sesión de transacción de MongoDB
        products_collection: Colección de productos
        items: Lista de items con product_id y quantity a restar
        
    Raises:
        HTTPException: Si la actualización falla
    """
    for item in items:
        product_id = item.get("product_id")
        quantity = item.get("quantity")
        
        # Actualizar stock usando operación atómica
        result = await products_collection.update_one(
            {
                "_id": ObjectId(product_id),
                "stock": {"$gte": quantity}  # Solo actualiza si hay stock suficiente
            },
            {
                "$inc": {"stock": -quantity}  # Decrementar stock
            },
            session=session
        )
        
        if result.modified_count == 0:
            # Si no se modificó, significa que no había stock suficiente
            # (race condition detectada)
            product = await products_collection.find_one(
                {"_id": ObjectId(product_id)},
                session=session
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Stock insuficiente para '{product['name']}' debido a compra concurrente. Por favor, intenta nuevamente."
            )
        
        logger.info(f"Stock actualizado para producto {product_id}: -{quantity} unidades")

async def rollback_stock(
    session: AsyncIOMotorClientSession,
    products_collection,
    items: List[Dict[str, any]]
) -> None:
    """
    Revierte la actualización de stock (para casos de error).
    Debe llamarse dentro de una transacción.
    
    Args:
        session: Sesión de transacción de MongoDB
        products_collection: Colección de productos
        items: Lista de items con product_id y quantity a devolver
    """
    for item in items:
        product_id = item.get("product_id")
        quantity = item.get("quantity")
        
        await products_collection.update_one(
            {"_id": ObjectId(product_id)},
            {"$inc": {"stock": quantity}},  # Incrementar stock
            session=session
        )
        
        logger.info(f"Stock revertido para producto {product_id}: +{quantity} unidades")
