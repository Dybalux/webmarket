from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from bson import ObjectId

from models import Cart, CartItem, CartDetailed, CartItemDetailed, Product, TokenData, UserRole
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
@router.get("/", response_model=CartDetailed)
async def get_cart(
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection),
    current_verified_user: TokenData = Depends(get_current_verified_user) 
):
    """
    Obtiene el carrito de compras del usuario autenticado con información detallada.
    Incluye datos completos de productos y combos (nombre, precio, imagen, stock, etc.).
    Optimizado con bulk queries para mejor performance.
    Requiere que el usuario haya verificado su mayoría de edad.
    """
    # Obtener el carrito básico
    cart = await get_user_cart(carts_collection, user_id)
    
    if not cart.items:
        # Carrito vacío, devolver directamente
        return CartDetailed(id=cart.id, user_id=cart.user_id, items=[])
    
    # OPTIMIZACIÓN: Obtener todos los IDs para hacer bulk queries
    all_item_ids = [ObjectId(item.product_id) for item in cart.items]
    
    # Bulk query para productos (proyección de campos necesarios)
    products_cursor = products_collection.find(
        {"_id": {"$in": all_item_ids}},
        {"name": 1, "price": 1, "image_url": 1, "stock": 1}
    )
    products_dict = {str(p["_id"]): p async for p in products_cursor}
    
    # Bulk query para combos
    combos_collection = get_collection("combos")
    combos_cursor = combos_collection.find(
        {"_id": {"$in": all_item_ids}},
        {"name": 1, "price": 1, "image_url": 1, "items": 1, "active": 1}
    )
    combos_dict = {str(c["_id"]): c async for c in combos_cursor}
    
    # Obtener IDs de productos dentro de combos para una sola query adicional
    combo_product_ids = set()
    for combo in combos_dict.values():
        for combo_item in combo.get("items", []):
            combo_product_ids.add(ObjectId(combo_item["product_id"]))
    
    # Bulk query para productos de combos
    combo_products_dict = {}
    if combo_product_ids:
        combo_products_cursor = products_collection.find(
            {"_id": {"$in": list(combo_product_ids)}},
            {"name": 1, "image_url": 1}
        )
        combo_products_dict = {str(p["_id"]): p async for p in combo_products_cursor}
    
    # Enriquecer items usando los datos obtenidos
    enriched_items = []
    
    for item in cart.items:
        product_id_str = item.product_id
        
        # Verificar si es producto
        if product_id_str in products_dict:
            product = products_dict[product_id_str]
            enriched_item = CartItemDetailed(
                product_id=product_id_str,
                quantity=item.quantity,
                item_type="product",
                name=product["name"],
                price=product["price"],
                image_url=product.get("image_url"),
                stock=product.get("stock", 0),
                combo_items=None
            )
            enriched_items.append(enriched_item)
        
        # Verificar si es combo
        elif product_id_str in combos_dict:
            combo = combos_dict[product_id_str]
            
            # Construir información de items del combo
            combo_items_info = []
            for combo_item in combo.get("items", []):
                combo_prod_id = combo_item["product_id"]
                if combo_prod_id in combo_products_dict:
                    prod = combo_products_dict[combo_prod_id]
                    combo_items_info.append({
                        "product_id": combo_prod_id,
                        "name": prod["name"],
                        "quantity": combo_item["quantity"],
                        "image_url": prod.get("image_url")
                    })
            
            enriched_item = CartItemDetailed(
                product_id=product_id_str,
                quantity=item.quantity,
                item_type="combo",
                name=combo["name"],
                price=combo["price"],
                image_url=combo.get("image_url"),
                stock=None,
                combo_items=combo_items_info
            )
            enriched_items.append(enriched_item)
        else:
            # Item no encontrado
            logger.warning(f"Item {product_id_str} en carrito de usuario {user_id} no encontrado")
    
    # Construir respuesta enriquecida
    enriched_cart = CartDetailed(
        id=cart.id,
        user_id=cart.user_id,
        items=enriched_items
    )
    
    return enriched_cart

@router.post("/add", response_model=Cart)
async def add_to_cart(
    cart_item_data: CartItem,
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection),
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Añade un producto o combo al carrito de compras del usuario o actualiza su cantidad.
    Requiere que el usuario haya verificado su mayoría de edad.
    """
    # 1. Verificar que el ID sea válido
    if not ObjectId.is_valid(cart_item_data.product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto/combo inválido.")
    
    # 2. Intentar buscar como producto primero
    product_db = await products_collection.find_one({"_id": ObjectId(cart_item_data.product_id)})
    
    # 3. Si no es producto, intentar buscar como combo
    is_combo = False
    if not product_db:
        combos_collection = get_collection("combos")
        combo_db = await combos_collection.find_one({"_id": ObjectId(cart_item_data.product_id), "active": True})
        
        if combo_db:
            is_combo = True
            logger.info(f"Item {cart_item_data.product_id} identificado como combo: {combo_db['name']}")
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Producto o combo no encontrado."
            )
    
    # 4. Obtener o crear el carrito del usuario
    cart = await get_user_cart(carts_collection, user_id)

    # 5. Calcular la cantidad total que tendría el item en el carrito
    existing_quantity = 0
    for item in cart.items:
        if item.product_id == cart_item_data.product_id:
            existing_quantity = item.quantity
            break
    
    total_quantity = existing_quantity + cart_item_data.quantity
    
    # 6. Validar stock según el tipo de item
    if is_combo:
        # Para combos, validar el stock de cada producto componente
        for combo_item in combo_db["items"]:
            product_id = combo_item["product_id"]
            quantity_per_combo = combo_item["quantity"]
            total_needed = quantity_per_combo * total_quantity
            
            product = await products_collection.find_one({"_id": ObjectId(product_id)})
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Producto {product_id} del combo no encontrado."
                )
            
            if product.get("stock", 0) < total_needed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Stock insuficiente para '{product['name']}' (parte del combo '{combo_db['name']}'). Disponible: {product.get('stock', 0)}, Necesario: {total_needed}."
                )
    else:
        # Para productos individuales, validar stock directamente
        if product_db.get("stock", 0) < total_quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stock insuficiente para el producto '{product_db['name']}'. Solo quedan {product_db.get('stock', 0)} unidades y ya tienes {existing_quantity} en el carrito."
            )

    # 7. Añadir/actualizar el item en el carrito
    found = False
    for item in cart.items:
        if item.product_id == cart_item_data.product_id:
            item.quantity = total_quantity  # Actualizar a la cantidad total
            found = True
            break
    
    if not found:
        cart.items.append(cart_item_data)
    
    # 8. Guardar el carrito actualizado
    await save_cart(carts_collection, cart)
    
    item_type = "combo" if is_combo else "producto"
    logger.info(f"Usuario {user_id} añadió/actualizó {item_type} {cart_item_data.product_id} en el carrito. Cantidad total: {total_quantity}")
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
    Actualiza la cantidad de un producto o combo específico en el carrito.
    Si la cantidad es 0, el producto/combo se elimina del carrito.
    Requiere que el usuario haya verificado su mayoría de edad.
    """
    # 1. Validar ID
    if not ObjectId.is_valid(cart_item_data.product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto/combo inválido.")
    
    # 2. Verificar si es producto o combo y validar stock si la cantidad es > 0
    if cart_item_data.quantity > 0:
        product_db = await products_collection.find_one({"_id": ObjectId(cart_item_data.product_id)})
        
        # Si no es producto, verificar si es combo
        is_combo = False
        if not product_db:
            combos_collection = get_collection("combos")
            combo_db = await combos_collection.find_one({"_id": ObjectId(cart_item_data.product_id), "active": True})
            
            if combo_db:
                is_combo = True
            else:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto o combo no encontrado.")
        
        # Validar stock según el tipo
        if is_combo:
            # Validar stock de cada producto del combo
            for combo_item in combo_db["items"]:
                product_id = combo_item["product_id"]
                quantity_per_combo = combo_item["quantity"]
                total_needed = quantity_per_combo * cart_item_data.quantity
                
                product = await products_collection.find_one({"_id": ObjectId(product_id)})
                if not product:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Producto {product_id} del combo no encontrado."
                    )
                
                if product.get("stock", 0) < total_needed:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Stock insuficiente para '{product['name']}' (parte del combo '{combo_db['name']}'). Disponible: {product.get('stock', 0)}, Necesario: {total_needed}."
                    )
        else:
            # Validar stock de producto individual
            if product_db.get("stock", 0) < cart_item_data.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Stock insuficiente para el producto '{product_db['name']}'. Solo quedan {product_db.get('stock', 0)} unidades."
                )
            
    # 3. Obtener el carrito del usuario
    cart = await get_user_cart(carts_collection, user_id)

    # 4. Actualizar la cantidad o eliminar
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El producto/combo no está en el carrito.")

    cart.items = updated_items
    
    # 5. Guardar el carrito actualizado
    await save_cart(carts_collection, cart)
    logger.info(f"Usuario {user_id} actualizó cantidad de item {cart_item_data.product_id} a {cart_item_data.quantity} en el carrito.")
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

@router.post("/cleanup")
async def cleanup_cart(
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection),
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Limpia automáticamente el carrito eliminando items que ya no existen o están inactivos.
    Devuelve el carrito limpio y la lista de items eliminados con sus razones.
    """
    cart = await get_user_cart(carts_collection, user_id)
    combos_collection = get_collection("combos")
    
    valid_items = []
    removed_items = []
    
    for item in cart.items:
        # Verificar si es un producto válido
        product = await products_collection.find_one({"_id": ObjectId(item.product_id)})
        
        if product:
            # Es un producto válido
            valid_items.append(item)
        else:
            # No es producto, verificar si es combo
            combo = await combos_collection.find_one({"_id": ObjectId(item.product_id)})
            
            if combo:
                # Es un combo, verificar si está activo
                if combo.get("active", False):
                    valid_items.append(item)
                else:
                    # Combo desactivado
                    removed_items.append({
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "reason": f"Combo desactivado: {combo['name']}"
                    })
                    logger.info(f"Removido combo desactivado {item.product_id} del carrito de usuario {user_id}")
            else:
                # No existe ni como producto ni como combo
                removed_items.append({
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "reason": "Producto o combo no encontrado"
                })
                logger.info(f"Removido item inexistente {item.product_id} del carrito de usuario {user_id}")
    
    # Actualizar carrito con items válidos
    cart.items = valid_items
    await save_cart(carts_collection, cart)
    
    return {
        "cart": cart,
        "removed_items": removed_items,
        "removed_count": len(removed_items)
    }

@router.get("/validate-stock")
async def validate_cart_stock(
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection),
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Valida el stock disponible para todos los items en el carrito sin modificarlo.
    Útil para verificaciones en tiempo real y mostrar advertencias al usuario.
    """
    cart = await get_user_cart(carts_collection, user_id)
    combos_collection = get_collection("combos")
    
    validation_results = []
    
    for item in cart.items:
        # Verificar si es producto
        product = await products_collection.find_one({"_id": ObjectId(item.product_id)})
        
        if product:
            # Validar stock de producto
            available = product.get("stock", 0) >= item.quantity
            
            validation_results.append({
                "product_id": item.product_id,
                "quantity_in_cart": item.quantity,
                "available": available,
                "stock": product.get("stock", 0),
                "item_type": "product",
                "name": product["name"]
            })
        else:
            # Verificar si es combo
            combo = await combos_collection.find_one({"_id": ObjectId(item.product_id)})
            
            if combo:
                # Validar stock de cada producto del combo
                available = True
                limiting_product = None
                
                for combo_item in combo.get("items", []):
                    prod = await products_collection.find_one({"_id": ObjectId(combo_item["product_id"])})
                    if prod:
                        needed = combo_item["quantity"] * item.quantity
                        stock = prod.get("stock", 0)
                        
                        if stock < needed:
                            available = False
                            limiting_product = {
                                "name": prod["name"],
                                "stock": stock,
                                "needed": needed
                            }
                            break
                
                result = {
                    "product_id": item.product_id,
                    "quantity_in_cart": item.quantity,
                    "available": available,
                    "item_type": "combo",
                    "name": combo["name"],
                    "active": combo.get("active", False)
                }
                
                if limiting_product:
                    result["limiting_product"] = limiting_product
                
                validation_results.append(result)
            else:
                # Item no encontrado
                validation_results.append({
                    "product_id": item.product_id,
                    "quantity_in_cart": item.quantity,
                    "available": False,
                    "item_type": "unknown",
                    "name": "Item no encontrado",
                    "error": "Producto o combo no existe"
                })
    
    return {
        "items": validation_results,
        "all_available": all(item["available"] for item in validation_results)
    }

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
