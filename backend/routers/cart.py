# backend/routers/cart.py (CORREGIDO)
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from bson import ObjectId

from models import Cart, CartItem, Product, TokenData, UserRole
from database import get_database, get_collection
from security import get_current_active_user_id, get_current_verified_user # Importamos dependencia para usuario activo y verificado

import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Colecciones de MongoDB
def get_carts_collection(db=Depends(get_database)):
    return get_collection("carts")

def get_products_collection(db=Depends(get_database)):
    return get_collection("products")

# --- Funciones auxiliares para el carrito ---
async def get_user_cart(carts_collection, products_collection, user_id: str) -> Optional[Cart]:
    """Obtiene el carrito de un usuario. ¡Popula los detalles del producto!"""
    cart_db = await carts_collection.find_one({"user_id": user_id})
    
    if not cart_db:
        # Si no existe, creamos un carrito vacío para el usuario
        new_cart_data = {"user_id": user_id, "items": []}
        result = await carts_collection.insert_one(new_cart_data)
        new_cart_data["_id"] = str(result.inserted_id)
        return Cart(**new_cart_data)

    # --- LÓGICA DE "POPULATE" ---
    populated_items = []
    for item_data in cart_db.get("items", []):
        product_id = item_data.get("product_id")
        if not ObjectId.is_valid(product_id):
            continue 
            
        product_db = await products_collection.find_one({"_id": ObjectId(product_id)})
        
        if product_db:
            item_with_details = {
                "product_id": str(product_db["_id"]),
                "quantity": item_data.get("quantity", 0),
                "name": product_db.get("name"),
                "price": product_db.get("price"),
                "image_url": product_db.get("image_url")
            }
            populated_items.append(item_with_details)
    
    cart_db["items"] = populated_items
    cart_db["_id"] = str(cart_db["_id"])
    return Cart(**cart_db)

async def save_cart(carts_collection, cart: Cart):
    """Guarda o actualiza un carrito en la base de datos."""
    
    # Convertimos los items (que ahora tienen detalles) 
    # de vuelta a items simples para guardar en la DB.
    simple_items = [
        {"product_id": item.product_id, "quantity": item.quantity} 
        for item in cart.items
    ]
    
    cart_dict = cart.model_dump(by_alias=True, exclude_unset=True)
    
    if cart.id:
        await carts_collection.update_one(
            {"_id": ObjectId(cart.id)},
            {"$set": {"items": simple_items, "user_id": cart_dict["user_id"]}}
        )
    else:
        cart_dict["items"] = simple_items # Aseguramos guardar items simples
        result = await carts_collection.insert_one(cart_dict)
        cart.id = str(result.inserted_id)
    return cart

# --- Endpoints del carrito ---
@router.get("/", response_model=Cart)
async def get_cart(
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection), # Dependencia añadida
    current_verified_user: TokenData = Depends(get_current_verified_user) 
):
    """
    Obtiene el carrito de compras del usuario autenticado.
    """
    cart = await get_user_cart(carts_collection, products_collection, user_id)
    return cart

@router.post("/add", response_model=Cart)
async def add_to_cart(
    cart_item_data: CartItem,
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection),
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Añade un producto al carrito de compras del usuario o actualiza su cantidad.
    """
    # 1. Verificar que el producto exista y tenga stock suficiente
    product_db = await products_collection.find_one({"_id": ObjectId(cart_item_data.product_id)})
    if not product_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")
    
    if product_db.get("stock", 0) < cart_item_data.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stock insuficiente para el producto '{product_db['name']}'. Solo quedan {product_db.get('stock', 0)} unidades."
        )

    # 2. Obtener o crear el carrito del usuario
    # --- ¡ARREGLO AQUÍ! ---
    cart = await get_user_cart(carts_collection, products_collection, user_id)

    # 3. Añadir/actualizar el producto en el carrito
    found = False
    for item in cart.items:
        if item.product_id == cart_item_data.product_id:
            item.quantity += cart_item_data.quantity # Sumar la cantidad
            found = True
            break
    
    if not found:
        # Si no lo encontró, populamos los datos del nuevo item
        cart_item_data.name = product_db.get("name")
        cart_item_data.price = product_db.get("price")
        cart_item_data.image_url = product_db.get("image_url")
        cart.items.append(cart_item_data)
    
    # 4. Guardar el carrito actualizado
    await save_cart(carts_collection, cart)
    logger.info(f"Usuario {user_id} añadió/actualizó producto {cart_item_data.product_id} en el carrito. Cantidad: {cart_item_data.quantity}")
    return cart

@router.put("/update", response_model=Cart)
async def update_cart_item_quantity(
    cart_item_data: CartItem,
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection),
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Actualiza la cantidad de un producto específico en el carrito.
    """
    # 1. Verificar stock si la cantidad es > 0
    if cart_item_data.quantity > 0:
        product_db = await products_collection.find_one({"_id": ObjectId(cart_item_data.product_id)})
        if not product_db:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")
        
        if product_db.get("stock", 0) < cart_item_data.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stock insuficiente para el producto '{product_db['name']}'. Solo quedan {product_db.get('stock', 0)} unidades."
            )
            
    # 2. Obtener el carrito del usuario
    # --- ¡ARREGLO AQUÍ! ---
    cart = await get_user_cart(carts_collection, products_collection, user_id)

    # 3. Actualizar la cantidad o eliminar
    updated_items = []
    found = False
    for item in cart.items:
        if item.product_id == cart_item_data.product_id:
            found = True
            if cart_item_data.quantity > 0:
                item.quantity = cart_item_data.quantity
                updated_items.append(item)
        else:
            updated_items.append(item)
    
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El producto no está en el carrito.")

    cart.items = updated_items
    
    # 4. Guardar el carrito actualizado
    await save_cart(carts_collection, cart)
    logger.info(f"Usuario {user_id} actualizó cantidad de producto {cart_item_data.product_id} a {cart_item_data.quantity} en el carrito.")
    return cart

@router.delete("/remove/{product_id}", response_model=Cart)
async def remove_from_cart(
    product_id: str,
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection), # <-- AÑADIDA DEPENDENCIA
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Elimina un producto del carrito de compras del usuario.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    # --- ¡ARREGLO AQUÍ! ---
    cart = await get_user_cart(carts_collection, products_collection, user_id)
    
    original_item_count = len(cart.items)
    cart.items = [item for item in cart.items if item.product_id != product_id]
    
    if len(cart.items) == original_item_count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El producto no está en el carrito.")

    await save_cart(carts_collection, cart)
    logger.info(f"Usuario {user_id} eliminó producto {product_id} del carrito.")
    return cart

@router.delete("/clear", response_model=Cart)
async def clear_cart(
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection), # <-- AÑADIDA DEPENDENCIA
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Vacía completamente el carrito de compras del usuario.
    """
    # --- ¡ARREGLO AQUÍ! ---
    cart = await get_user_cart(carts_collection, products_collection, user_id)
    cart.items = [] # Vaciar la lista de ítems
    await save_cart(carts_collection, cart)
    logger.info(f"Usuario {user_id} ha vaciado su carrito.")
    return cart