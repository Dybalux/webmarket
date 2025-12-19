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
async def get_user_cart(carts_collection, user_id: str) -> Optional[Cart]:
    """Obtiene el carrito de un usuario, o crea uno si no existe."""
    cart_db = await carts_collection.find_one({"user_id": user_id})
    if cart_db:
        cart_db["_id"] = str(cart_db["_id"]) # Convertir ObjectId a str para Pydantic
        return Cart(**cart_db)
    
    # Si no existe, creamos un carrito vacío para el usuario
    new_cart_data = {"user_id": user_id, "items": []}
    result = await carts_collection.insert_one(new_cart_data)
    new_cart_data["_id"] = str(result.inserted_id) # Aseguramos que el ID esté presente para Pydantic
    return Cart(**new_cart_data)

async def save_cart(carts_collection, cart: Cart):
    """Guarda o actualiza un carrito en la base de datos."""
    cart_dict = cart.model_dump(by_alias=True, exclude_unset=True)
    
    # Si el carrito ya tiene un _id, es una actualización
    if cart.id:
        await carts_collection.update_one(
            {"_id": ObjectId(cart.id)},
            {"$set": {"items": cart_dict["items"], "user_id": cart_dict["user_id"]}}
        )
    else: # Si no tiene _id, es un nuevo carrito
        result = await carts_collection.insert_one(cart_dict)
        cart.id = str(result.inserted_id) # Actualizamos el ID en el objeto Python
    return cart

# --- Endpoints del carrito ---
@router.get("/", response_model=Cart)
async def get_cart(
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    # Requiere que el usuario esté verificado para ver el carrito de bebidas alcohólicas
    # Opcional: podrías permitir ver el carrito sin verificar, pero no avanzar al checkout
    current_verified_user: TokenData = Depends(get_current_verified_user) 
):
    """
    Obtiene el carrito de compras del usuario autenticado. Si no existe, crea uno vacío.
    Requiere que el usuario haya verificado su mayoría de edad.
    """
    cart = await get_user_cart(carts_collection, user_id)
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
    Requiere que el usuario haya verificado su mayoría de edad.
    """
    # 1. Verificar que el producto exista
    product_db = await products_collection.find_one({"_id": ObjectId(cart_item_data.product_id)})
    if not product_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")
    
    # 2. Obtener o crear el carrito del usuario
    cart = await get_user_cart(carts_collection, user_id)

    # 3. Calcular la cantidad total que tendría el producto en el carrito
    existing_quantity = 0
    for item in cart.items:
        if item.product_id == cart_item_data.product_id:
            existing_quantity = item.quantity
            break
    
    total_quantity = existing_quantity + cart_item_data.quantity
    
    # 4. Verificar que el stock sea suficiente para la cantidad TOTAL
    if product_db.get("stock", 0) < total_quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stock insuficiente para el producto '{product_db['name']}'. Solo quedan {product_db.get('stock', 0)} unidades y ya tienes {existing_quantity} en el carrito."
        )

    # 5. Añadir/actualizar el producto en el carrito
    found = False
    for item in cart.items:
        if item.product_id == cart_item_data.product_id:
            item.quantity = total_quantity  # Actualizar a la cantidad total
            found = True
            break
    
    if not found:
        cart.items.append(cart_item_data)
    
    # 6. Guardar el carrito actualizado
    await save_cart(carts_collection, cart)
    logger.info(f"Usuario {user_id} añadió/actualizó producto {cart_item_data.product_id} en el carrito. Cantidad total: {total_quantity}")
    return cart

@router.put("/update", response_model=Cart)
async def update_cart_item_quantity(
    cart_item_data: CartItem, # product_id y la nueva cantidad total deseada
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection),
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Actualiza la cantidad de un producto específico en el carrito.
    Si la cantidad es 0, el producto se elimina del carrito.
    Requiere que el usuario haya verificado su mayoría de edad.
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
    cart = await get_user_cart(carts_collection, user_id)

    # 3. Actualizar la cantidad o eliminar
    updated_items = []
    found = False
    for item in cart.items:
        if item.product_id == cart_item_data.product_id:
            found = True
            if cart_item_data.quantity > 0:
                item.quantity = cart_item_data.quantity
                updated_items.append(item)
            # Si quantity es 0, simplemente no lo añadimos a updated_items (lo eliminamos)
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
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Elimina un producto del carrito de compras del usuario.
    Requiere que el usuario haya verificado su mayoría de edad.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    cart = await get_user_cart(carts_collection, user_id)
    
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
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Vacía completamente el carrito de compras del usuario.
    Requiere que el usuario haya verificado su mayoría de edad.
    """
    cart = await get_user_cart(carts_collection, user_id)
    cart.items = [] # Vaciar la lista de ítems
    await save_cart(carts_collection, cart)
    logger.info(f"Usuario {user_id} ha vaciado su carrito.")
    return cart
