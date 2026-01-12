from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from bson import ObjectId
from datetime import datetime

from models import Order, OrderCreate, OrderItem, OrderStatus, Product, Cart, TokenData, PaymentMethod
from database import get_database, get_collection
from security import get_current_active_user_id, get_current_verified_user, get_current_admin_user
from email_service import send_new_order_notification
# from stock_helpers import validate_and_reserve_stock, update_stock_atomic  # Descomenta cuando uses MongoDB M10+
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Colecciones de MongoDB
def get_orders_collection(db=Depends(get_database)):
    return get_collection("orders")

def get_products_collection(db=Depends(get_database)):
    return get_collection("products")

def get_carts_collection(db=Depends(get_database)):
    return get_collection("carts")

# Función helper para procesar combos
async def process_combo_item(combo_id: str, quantity: int, products_collection):
    """
    Procesa un combo y retorna los productos individuales que lo componen.
    
    Args:
        combo_id: ID del combo
        quantity: Cantidad de combos solicitados
        products_collection: Colección de productos
    
    Returns:
        dict con 'products_to_decrement' (lista de productos a restar stock) y 'total_price'
    """
    combos_collection = get_collection("combos")
    
    # Obtener el combo
    combo = await combos_collection.find_one({"_id": ObjectId(combo_id), "active": True})
    if not combo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Combo con ID {combo_id} no encontrado o inactivo."
        )
    
    products_to_decrement = []
    
    # Iterar sobre los items del combo
    for combo_item in combo["items"]:
        product_id = combo_item["product_id"]
        quantity_per_combo = combo_item["quantity"]
        total_quantity_needed = quantity_per_combo * quantity  # Cantidad total necesaria
        
        # Validar que el producto existe
        if not ObjectId.is_valid(product_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ID de producto inválido en combo: {product_id}"
            )
        
        product = await products_collection.find_one({"_id": ObjectId(product_id)})
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto {product_id} del combo no encontrado."
            )
        
        # Validar stock
        if product.get("stock", 0) < total_quantity_needed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Stock insuficiente para '{product['name']}' (parte del combo '{combo['name']}'). Disponible: {product.get('stock', 0)}, Necesario: {total_quantity_needed}."
            )
        
        # Agregar a la lista de productos a decrementar
        products_to_decrement.append({
            "id": ObjectId(product_id),
            "quantity_to_decrement": total_quantity_needed,
            "name": product["name"]
        })
    
    return {
        "products_to_decrement": products_to_decrement,
        "combo_name": combo["name"],
        "combo_price": combo["price"]
    }

# Endpoint público para obtener precios de envío

@router.get("/shipping-prices")
async def get_shipping_prices():
    """Endpoint público para obtener precios de envío"""
    try:
        settings_collection = get_collection("shipping_settings")
        settings = await settings_collection.find_one({})
        
        if not settings:
            return {
                "central_zone_price": 500.0,
                "remote_zone_price": 1000.0
            }
        
        return {
            "central_zone_price": settings["central_zone_price"],
            "remote_zone_price": settings["remote_zone_price"]
        }
    except Exception as e:
        logger.error(f"Error al obtener precios de envío: {e}", exc_info=True)
        # Devolver precios por defecto en caso de error
        return {
            "central_zone_price": 500.0,
            "remote_zone_price": 1000.0
        }

# Endpoint para crear un pedido

@router.post("/", response_model=Order, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: OrderCreate,
    payment_method: PaymentMethod = PaymentMethod.MERCADO_PAGO,  # Método de pago por defecto
    user_id: str = Depends(get_current_active_user_id),
    carts_collection = Depends(get_carts_collection),
    products_collection = Depends(get_products_collection),
    orders_collection = Depends(get_orders_collection),
    # Es crucial que el usuario esté verificado para hacer un pedido
    current_verified_user: TokenData = Depends(get_current_verified_user)
):
    """
    Crea un nuevo pedido a partir del carrito del usuario.
    - Valida el stock de los productos.
    - Decrementa el stock.
    - Vacía el carrito.
    - Permite seleccionar el método de pago (Mercado Pago o Transferencia).
    Requiere que el usuario haya verificado su mayoría de edad.
    
    NOTA: La versión con transacciones está comentada porque MongoDB Atlas M0 (gratuito)
    no soporta transacciones. Para habilitar transacciones, actualiza a M10+ y descomenta
    el código en la sección "VERSIÓN CON TRANSACCIONES" más abajo.
    """
    # 1. Obtener el carrito del usuario
    cart_db = await carts_collection.find_one({"user_id": user_id})
    if not cart_db or not cart_db.get("items"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tu carrito está vacío.")
    
    cart_db["_id"] = str(cart_db["_id"])
    cart = Cart(**cart_db)
    order_items: List[OrderItem] = []
    total_amount = 0.0

    # 2. Iterar sobre los ítems del carrito para validar y construir el pedido
    # Ahora soportamos tanto productos individuales como combos
    product_ids_to_update = []
    combos_collection = get_collection("combos")
    
    for item in cart.items:
        # Primero intentar buscar como producto
        product = await products_collection.find_one({"_id": ObjectId(item.product_id)})
        
        # Si no es un producto, intentar buscar como combo
        if not product:
            # Buscar el combo (sin filtrar por active primero para dar mejor mensaje de error)
            combo = await combos_collection.find_one({"_id": ObjectId(item.product_id)})
            
            if combo:
                # Validar que el combo esté activo
                if not combo.get("active", False):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"El combo '{combo['name']}' ya no está disponible. Por favor, elimínalo de tu carrito antes de continuar."
                    )
                
                # ES UN COMBO ACTIVO
                logger.info(f"Procesando combo '{combo['name']}' (cantidad: {item.quantity})")
                
                # Procesar el combo y obtener los productos que lo componen
                combo_data = await process_combo_item(item.product_id, item.quantity, products_collection)
                
                # Agregar los productos del combo a la lista de actualización de stock
                product_ids_to_update.extend(combo_data["products_to_decrement"])
                
                # Crear el OrderItem para el combo
                order_item = OrderItem(
                    product_id=ObjectId(item.product_id),
                    name=f"{combo_data['combo_name']} (Combo)",
                    quantity=item.quantity,
                    price_at_purchase=combo_data["combo_price"]
                )
                order_items.append(order_item)
                total_amount += order_item.price_at_purchase * order_item.quantity
                
            else:
                # No es ni producto ni combo
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Producto o Combo con ID {item.product_id} no encontrado."
                )
        else:
            # ES UN PRODUCTO NORMAL
            if product.get("stock", 0) < item.quantity:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Stock insuficiente para '{product['name']}'. Disponible: {product.get('stock', 0)}, Solicitado: {item.quantity}."
                )

            # Construir el OrderItem con los datos actuales del producto
            order_item = OrderItem(
                product_id=product["_id"],
                name=product["name"],
                quantity=item.quantity,
                price_at_purchase=product["price"]
            )
            order_items.append(order_item)
            total_amount += order_item.price_at_purchase * order_item.quantity
            
            # Guardar la info para actualizar el stock después
            product_ids_to_update.append({
                "id": ObjectId(item.product_id),
                "quantity_to_decrement": item.quantity
            })

    # Validar zona de envío
    if order_data.shipping_zone not in ["central", "remote"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zona de envío inválida. Debe ser 'central' o 'remote'."
        )
    
    # Obtener precio de envío según zona
    settings_collection = get_collection("shipping_settings")
    settings = await settings_collection.find_one({})
    
    if order_data.shipping_zone == "central":
        shipping_cost = settings.get("central_zone_price", 500.0) if settings else 500.0
    else:  # remote
        shipping_cost = settings.get("remote_zone_price", 1000.0) if settings else 1000.0
    
    # Calcular total incluyendo envío
    total_with_shipping = total_amount + shipping_cost
    
    # 3. Crear el documento del pedido
    new_order = Order(
        user_id=user_id,
        items=order_items,
        total_amount=total_with_shipping,  # Total con envío incluido
        status=OrderStatus.PENDING,
        shipping_address=order_data.shipping_address,
        shipping_zone=order_data.shipping_zone,
        shipping_cost=shipping_cost,
        payment_method=payment_method  # Guardar el método de pago seleccionado
    )
    
    order_dict = new_order.model_dump(exclude={"_id"}, by_alias=False)
    result = await orders_collection.insert_one(order_dict)
    
    if not result.inserted_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No se pudo crear el pedido.")

    # 4. Decrementar el stock de los productos
    for p in product_ids_to_update:
        await products_collection.update_one(
            {"_id": p["id"]},
            {"$inc": {"stock": -p["quantity_to_decrement"]}}
        )

    # 5. Vaciar el carrito del usuario
    await carts_collection.update_one(
        {"user_id": user_id},
        {"$set": {"items": []}}
    )
    
    logger.info(f"Pedido {result.inserted_id} creado para el usuario {user_id}.")
    
    created_order = await orders_collection.find_one({"_id": result.inserted_id})
    
    # 6. Enviar notificación por email al admin usando SendGrid
    try:
        # Obtener email del usuario
        users_collection = get_collection("users")
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        user_email = user.get("email", "email-no-disponible") if user else "email-no-disponible"
        
        await send_new_order_notification(
            order_id=str(result.inserted_id),
            user_email=user_email,
            total_amount=total_with_shipping,  # Enviar total con envío
            payment_method=payment_method.value
        )
    except Exception as e:
        # No romper si falla el email
        logger.error(f"Error al enviar notificación de email: {e}")
    
    return Order(**created_order)

    # ============================================================================
    # VERSIÓN CON TRANSACCIONES (Requiere MongoDB M10+ o Replica Set)
    # ============================================================================
    # Descomenta este código cuando actualices a MongoDB Atlas M10+ o superior
    # y comenta la versión simple de arriba
    # ============================================================================
    """
    # 1. Obtener el carrito del usuario
    cart_db = await carts_collection.find_one({"user_id": user_id})
    if not cart_db or not cart_db.get("items"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tu carrito está vacío.")
    
    cart_db["_id"] = str(cart_db["_id"])
    cart = Cart(**cart_db)
    
    # 2. Iniciar transacción de MongoDB para operaciones atómicas
    from database import db as db_instance
    client = db_instance.client
    
    async with await client.start_session() as session:
        async with session.start_transaction():
            try:
                # 3. Validar y reservar stock de forma atómica
                cart_items_dict = [{"product_id": item.product_id, "quantity": item.quantity} for item in cart.items]
                validated_products = await validate_and_reserve_stock(
                    session,
                    products_collection,
                    cart_items_dict
                )
                
                # 4. Construir los items de la orden con precios actuales
                order_items: List[OrderItem] = []
                total_amount = 0.0
                
                for validated_product in validated_products:
                    order_item = OrderItem(
                        product_id=ObjectId(validated_product["product_id"]),
                        name=validated_product["name"],
                        quantity=validated_product["quantity"],
                        price_at_purchase=validated_product["price"]
                    )
                    order_items.append(order_item)
                    total_amount += order_item.price_at_purchase * order_item.quantity
                
                # 5. Crear el documento del pedido
                new_order = Order(
                    user_id=user_id,
                    items=order_items,
                    total_amount=total_amount,
                    status=OrderStatus.PENDING,
                    shipping_address=order_data.shipping_address
                )
                
                order_dict = new_order.model_dump(exclude={"_id"}, by_alias=False)
                result = await orders_collection.insert_one(order_dict, session=session)
                
                if not result.inserted_id:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="No se pudo crear el pedido."
                    )
                
                # 6. Actualizar stock de forma atómica
                await update_stock_atomic(session, products_collection, cart_items_dict)
                
                # 7. Vaciar el carrito del usuario
                await carts_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"items": []}},
                    session=session
                )
                
                # 8. Commit de la transacción (automático al salir del contexto)
                logger.info(f"Pedido {result.inserted_id} creado exitosamente para el usuario {user_id} usando transacción.")
                
                # 9. Obtener y devolver el pedido creado
                created_order = await orders_collection.find_one({"_id": result.inserted_id})
                return Order(**created_order)
                
            except HTTPException:
                # Re-lanzar excepciones HTTP (la transacción se revertirá automáticamente)
                raise
            except Exception as e:
                # Cualquier otro error también revertirá la transacción
                logger.error(f"Error al crear pedido: {e}", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Error al procesar el pedido. Por favor, intenta nuevamente."
                )
    """


@router.get("/me", response_model=List[Order])
async def get_my_orders(
    user_id: str = Depends(get_current_active_user_id),
    orders_collection = Depends(get_orders_collection)
):
    """Obtiene el historial de pedidos del usuario autenticado."""
    orders_cursor = orders_collection.find({"user_id": user_id}).sort("created_at", -1)
    return [Order(**order) async for order in orders_cursor]


@router.post("/{order_id}/select-payment-method", response_model=Order)
async def select_payment_method(
    order_id: str,
    payment_method: PaymentMethod,
    user_id: str = Depends(get_current_active_user_id),
    orders_collection = Depends(get_orders_collection)
):
    """
    Permite seleccionar o cambiar el método de pago para un pedido existente.
    Solo se puede cambiar si el pedido está en estado PENDING.
    """
    # 1. Validar el ID
    if not ObjectId.is_valid(order_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de pedido inválido.")
    
    # 2. Obtener el pedido
    order = await orders_collection.find_one({"_id": ObjectId(order_id)})
    
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado.")
    
    # 3. Verificar que el pedido pertenece al usuario
    if order["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este pedido no te pertenece.")
    
    # 4. Verificar que el pedido está en estado PENDING
    if order["status"] != OrderStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se puede cambiar el método de pago. El pedido está en estado '{order['status']}'."
        )
    
    # 5. Actualizar el método de pago
    await orders_collection.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {
            "payment_method": payment_method.value,
            "updated_at": datetime.utcnow()
        }}
    )
    
    logger.info(f"Usuario {user_id} seleccionó método de pago '{payment_method.value}' para el pedido {order_id}.")
    
    # 6. Devolver el pedido actualizado
    updated_order = await orders_collection.find_one({"_id": ObjectId(order_id)})
    return Order(**updated_order)


@router.get("/{order_id}", response_model=Order)
async def get_order_details(
    order_id: str,
    user_id: str = Depends(get_current_active_user_id),
    orders_collection = Depends(get_orders_collection)
):
    """
    Obtiene los detalles de un pedido específico del usuario autenticado.
    Verifica que el pedido pertenezca al usuario que lo solicita.
    """
    if not ObjectId.is_valid(order_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de pedido inválido.")
    
    order = await orders_collection.find_one({"_id": ObjectId(order_id)})
    
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado.")
    
    if order["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para ver este pedido.")
        
    return Order(**order)


# --- Endpoints para Administradores ---

@router.put("/admin/{order_id}/status", response_model=Order, tags=["Admin"])
async def update_order_status(
    order_id: str,
    new_status: OrderStatus, # Recibe el nuevo estado directamente como un valor del enum
    orders_collection = Depends(get_orders_collection),
    products_collection = Depends(get_products_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Actualiza el estado de un pedido.
    Requiere permisos de administrador.
    """
    # 1. Validar el ID
    if not ObjectId.is_valid(order_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de pedido inválido.")
    
    # 2. Obtener el pedido actual
    current_order = await orders_collection.find_one({"_id": ObjectId(order_id)})
    if not current_order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado.")
    current_status = str(current_order["status"])

    # 3. Reposición de stock si corresponde
    # Lógica de reposición de stock
    if new_status in [OrderStatus.CANCELLED, OrderStatus.REFUNDED] and current_status not in [
    OrderStatus.CANCELLED.value, OrderStatus.REFUNDED.value
    ]:
        logger.info(f"El pedido {order_id} se está cancelando/reembolsando. Reponiendo stock...")
    for item in current_order["items"]:
        try:
            product_oid = ObjectId(item["product_id"])
        except Exception:
            logger.error(f"El product_id {item['product_id']} no es válido, no se repone stock.")
            continue

        result = await products_collection.update_one(
            {"_id": product_oid},
            {"$inc": {"stock": item["quantity"]}}
        )

        if result.modified_count:
            logger.info(f"Stock del producto {item['product_id']} incrementado en {item['quantity']}.")
        else:
            logger.warning(f"No se encontró producto con id {item['product_id']} para reponer stock.")

   # 4. Actualizamos el estado del pedido
    await orders_collection.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"status": new_status.value, "updated_at": datetime.utcnow()}}
    )
    
    # 5. Devolver el pedido actualizado
    updated_order = await orders_collection.find_one({"_id": ObjectId(order_id)})
    logger.info(f"Admin {current_admin_user.username} actualizó el estado del pedido {order_id} a '{new_status.value}'.")
    return Order(**updated_order)