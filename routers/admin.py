from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from models import Order, UserResponse, OrderStatus, UserRole, TokenData, ShippingSettings, BulkPriceUpdate, SystemSettings
from database import get_database, get_collection
from security import get_current_admin_user
from utils.sanitize import escape_regex
from utils.money import from_decimal128, quantize_money, decimalize_doc
import audit_logger
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Sort-field whitelists (F-010) ---
ALLOWED_USER_SORT_FIELDS: frozenset[str] = frozenset(
    {"created_at", "username", "email", "role", "updated_at"}
)
ALLOWED_ORDER_SORT_FIELDS: frozenset[str] = frozenset(
    {"created_at", "total_amount", "status"}
)

# Colecciones de MongoDB
def get_users_collection(db=Depends(get_database)):
    return get_collection("users")

def get_orders_collection(db=Depends(get_database)):
    return get_collection("orders")

def get_products_collection(db=Depends(get_database)):
    return get_collection("products")


# --- Endpoint de Estadísticas ---

@router.get("/stats", tags=["Admin"])
async def get_admin_stats(
    users_collection = Depends(get_users_collection),
    products_collection = Depends(get_products_collection),
    orders_collection = Depends(get_orders_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Obtiene estadísticas generales del sistema.
    Requiere permisos de administrador.
    """
    try:
        # Total de usuarios
        total_users = await users_collection.count_documents({})
        
        # Total de productos
        total_products = await products_collection.count_documents({})
        
        # Total de pedidos por estado
        total_orders = await orders_collection.count_documents({})
        pending_orders = await orders_collection.count_documents({"status": OrderStatus.PENDING.value})
        processing_orders = await orders_collection.count_documents({"status": OrderStatus.PROCESSING.value})
        completed_orders = await orders_collection.count_documents({"status": OrderStatus.DELIVERED.value})
        cancelled_orders = await orders_collection.count_documents({"status": OrderStatus.CANCELLED.value})
        
        # Ingresos totales (suma de todos los pedidos completados)
        pipeline_total_revenue = [
            {"$match": {"status": OrderStatus.DELIVERED.value}},
            {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}
        ]
        total_revenue_result = await orders_collection.aggregate(pipeline_total_revenue).to_list(1)
        total_revenue_raw = total_revenue_result[0]["total"] if total_revenue_result else 0
        total_revenue = quantize_money(from_decimal128(total_revenue_raw))

        # Ingresos del último mes
        last_month = datetime.now(tz=timezone.utc) - timedelta(days=30)
        pipeline_monthly_revenue = [
            {
                "$match": {
                    "status": OrderStatus.DELIVERED.value,
                    "created_at": {"$gte": last_month}
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}
        ]
        monthly_revenue_result = await orders_collection.aggregate(pipeline_monthly_revenue).to_list(1)
        monthly_revenue_raw = monthly_revenue_result[0]["total"] if monthly_revenue_result else 0
        monthly_revenue = quantize_money(from_decimal128(monthly_revenue_raw))
        
        # Productos con bajo stock (< 10 unidades)
        low_stock_products = await products_collection.count_documents({"stock": {"$lt": 10}})
        
        # Usuarios verificados
        verified_users = await users_collection.count_documents({"age_verified": True})
        
        logger.info(f"Admin {current_admin_user.username} consultó las estadísticas del sistema.")
        
        return {
            "users": {
                "total": total_users,
                "verified": verified_users,
                "unverified": total_users - verified_users
            },
            "products": {
                "total": total_products,
                "low_stock": low_stock_products
            },
            "orders": {
                "total": total_orders,
                "pending": pending_orders,
                "processing": processing_orders,
                "completed": completed_orders,
                "cancelled": cancelled_orders
            },
            "revenue": {
                "total": total_revenue,
                "last_30_days": monthly_revenue
            }
        }
    except Exception as e:
        logger.error(f"Error al obtener estadísticas: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener estadísticas del sistema."
        )


# --- Endpoint de Gestión de Usuarios ---

@router.get("/users", response_model=dict, tags=["Admin"])
async def get_admin_users(
    users_collection = Depends(get_users_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user),
    skip: int = Query(0, ge=0, description="Número de usuarios a saltar para paginación"),
    limit: int = Query(20, ge=1, le=100, description="Número máximo de usuarios a devolver"),
    search: Optional[str] = Query(None, min_length=2, description="Buscar por email o username"),
    role: Optional[UserRole] = Query(None, description="Filtrar por rol"),
    age_verified: Optional[bool] = Query(None, description="Filtrar por verificación de edad"),
    sort_by: str = Query("created_at", description="Campo por el cual ordenar"),
    sort_order: int = Query(-1, description="Orden: 1 ascendente, -1 descendente")
):
    """
    [Admin] Obtiene la lista completa de usuarios con opciones de filtrado y paginación.
    Requiere permisos de administrador.
    """
    # Sort-field validation BEFORE try (ADR-2: HTTPException inside try → 500)
    if sort_by not in ALLOWED_USER_SORT_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sort field: '{sort_by}'. Allowed: {', '.join(sorted(ALLOWED_USER_SORT_FIELDS))}",
        )

    try:
        # Construir query
        query = {}
        
        if search:
            safe_search = escape_regex(search)
            query["$or"] = [
                {"username": {"$regex": safe_search, "$options": "i"}},
                {"email": {"$regex": safe_search, "$options": "i"}}
            ]
        
        if role:
            query["role"] = role.value
        
        if age_verified is not None:
            query["age_verified"] = age_verified
        
        # Contar total de usuarios que coinciden con el filtro
        total = await users_collection.count_documents(query)
        
        # Obtener usuarios con paginación
        users_cursor = users_collection.find(query).sort(sort_by, sort_order).skip(skip).limit(limit)
        users_list = []
        
        async for user_doc in users_cursor:
            # Excluir el hash de la contraseña de la respuesta
            user_doc.pop("hashed_password", None)
            users_list.append(UserResponse(**user_doc))
        
        logger.info(f"Admin {current_admin_user.username} consultó la lista de usuarios (total: {total}).")
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "users": users_list
        }
    except Exception as e:
        logger.error(f"Error al obtener usuarios: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener la lista de usuarios."
        )


# --- Endpoint de Gestión de Pedidos ---

@router.get("/orders", response_model=dict, tags=["Admin"])
async def get_admin_orders(
    orders_collection = Depends(get_orders_collection),
    users_collection = Depends(get_users_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user),
    skip: int = Query(0, ge=0, description="Número de pedidos a saltar para paginación"),
    limit: int = Query(20, ge=1, le=100, description="Número máximo de pedidos a devolver"),
    status_filter: Optional[OrderStatus] = Query(None, description="Filtrar por estado del pedido"),
    user_id: Optional[str] = Query(None, description="Filtrar por ID de usuario"),
    start_date: Optional[datetime] = Query(None, description="Fecha de inicio para filtrar pedidos"),
    end_date: Optional[datetime] = Query(None, description="Fecha de fin para filtrar pedidos"),
    sort_by: str = Query("created_at", description="Campo por el cual ordenar"),
    sort_order: int = Query(-1, description="Orden: 1 ascendente, -1 descendente")
):
    """
    [Admin] Obtiene la lista completa de pedidos con opciones de filtrado y paginación.
    Incluye información del usuario asociado a cada pedido.
    Requiere permisos de administrador.
    """
    # Sort-field validation BEFORE try (ADR-2: HTTPException inside try → 500)
    if sort_by not in ALLOWED_ORDER_SORT_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sort field: '{sort_by}'. Allowed: {', '.join(sorted(ALLOWED_ORDER_SORT_FIELDS))}",
        )

    try:
        # Construir query
        query = {}
        
        if status_filter:
            query["status"] = status_filter.value
        
        if user_id:
            query["user_id"] = user_id
        
        if start_date or end_date:
            query["created_at"] = {}
            if start_date:
                query["created_at"]["$gte"] = start_date
            if end_date:
                query["created_at"]["$lte"] = end_date
        
        # Contar total de pedidos que coinciden con el filtro
        total = await orders_collection.count_documents(query)
        
        # Obtener pedidos con paginación
        orders_cursor = orders_collection.find(query).sort(sort_by, sort_order).skip(skip).limit(limit)
        orders_list = []
        
        async for order_doc in orders_cursor:
            # Obtener información del usuario
            user_id_value = order_doc["user_id"]
            
            # Intentar buscar primero por el user_id como ObjectId (si es válido)
            user = None
            if ObjectId.is_valid(user_id_value):
                user = await users_collection.find_one({"_id": ObjectId(user_id_value)})
            
            # Si no lo encontró como ObjectId, el user_id podría estar como string
            if not user:
                user = await users_collection.find_one({"_id": user_id_value})
                
            user_info = {
                "username": user.get("username", "Desconocido") if user else "Desconocido",
                "email": user.get("email", "N/A") if user else "N/A"
            }
            
            # Agregar información del usuario al pedido
            order_with_user = Order(**order_doc)
            order_dict = order_with_user.model_dump()
            order_dict["user_info"] = user_info
            orders_list.append(order_dict)
        
        logger.info(f"Admin {current_admin_user.username} consultó la lista de pedidos (total: {total}).")
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "orders": orders_list
        }
    except Exception as e:
        logger.error(f"Error al obtener pedidos: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener la lista de pedidos."
        )


# --- Endpoint de Gestión de Roles ---

@router.put("/users/{user_id}/role", response_model=UserResponse, tags=["Admin"])
async def update_user_role(
    user_id: str,
    new_role: UserRole,
    request: Request,
    users_collection = Depends(get_users_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Cambia el rol de un usuario (admin o customer).
    Permite promover usuarios a admin o degradar admins a customer.
    Requiere permisos de administrador.
    """
    try:
        # 1. Validar el ID
        if not ObjectId.is_valid(user_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID de usuario inválido."
            )
        
        # 2. Obtener el usuario
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado."
            )
        
        # 3. Prevenir que el admin se quite sus propios permisos
        if str(user["_id"]) == current_admin_user.user_id and new_role == UserRole.CUSTOMER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes quitarte tus propios permisos de administrador."
            )
        
        current_role = user.get("role", UserRole.CUSTOMER.value)
        
        # 4. Actualizar el rol
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"role": new_role.value}}
        )
        
        # 5. Log de la acción
        action = "promovido a admin" if new_role == UserRole.ADMIN else "degradado a customer"
        logger.info(
            f"Admin {current_admin_user.username} {action} al usuario {user['username']} "
            f"(de {current_role} a {new_role.value})"
        )
        
        # 6. Devolver el usuario actualizado
        updated_user = await users_collection.find_one({"_id": ObjectId(user_id)})
        updated_user.pop("hashed_password", None)  # No devolver la contraseña
        
        await audit_logger.log_audit(
            audit_logger.AuditEvent.ADMIN_ROLE_CHANGED, request,
            {
                "admin_id": current_admin_user.user_id,
                "target_user": user["username"],
                "from_role": current_role,
                "to_role": new_role.value,
            },
        )
        return UserResponse(**updated_user)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al actualizar rol de usuario: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar el rol del usuario."
        )


# --- Endpoints de Configuración de Envíos ---

@router.get("/shipping-settings", response_model=ShippingSettings, tags=["Admin"])
async def get_shipping_settings(
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Obtiene la configuración de precios de envío.
    Requiere permisos de administrador.
    """
    try:
        settings_collection = get_collection("shipping_settings")
        settings = await settings_collection.find_one({})
        
        if not settings:
            # Crear configuración por defecto
            default_settings = {
                # Zona Central
                "central_zone_enabled": True,
                "central_zone_price": Decimal("0.00"),  # GRATIS para zona céntrica
                "central_zone_description": "🎁 ENVÍO GRATIS - Zona Céntrica de Santa María (centro y barrios aledaños)",
                # Zona Remota
                "remote_zone_enabled": True,
                "remote_zone_price": Decimal("1000.00"),
                "remote_zone_description": "🚛 Envío a Zonas Alejadas - Barrios periféricos y localidades cercanas",
                # Retiro en Persona
                "pickup_enabled": True,
                "pickup_address": "Configurar dirección en panel de administración",
                "pickup_price": Decimal("0.00"),
                "pickup_description": "🏪 Retiro en Persona - GRATIS en nuestro local",
                "updated_at": datetime.now(tz=timezone.utc)
            }
            result = await settings_collection.insert_one(default_settings)
            settings = await settings_collection.find_one({"_id": result.inserted_id})
        
        logger.info(f"Admin {current_admin_user.username} consultó la configuración de envíos.")
        return ShippingSettings(**settings)
    
    except Exception as e:
        logger.error(f"Error al obtener configuración de envíos: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener la configuración de envíos."
        )


@router.put("/shipping-settings", tags=["Admin"])
async def update_shipping_settings(
    # Zona Central
    central_zone_enabled: bool = Query(True, description="Habilitar envío a zona céntrica"),
    central_zone_price: Decimal = Query(..., ge=0, description="Precio de envío zona céntrica"),
    central_zone_description: str = Query(..., min_length=1, description="Descripción del envío a zona central"),
    # Zona Remota
    remote_zone_enabled: bool = Query(True, description="Habilitar envío a zonas alejadas"),
    remote_zone_price: Decimal = Query(..., gt=0, description="Precio de envío zonas lejanas"),
    remote_zone_description: str = Query(..., min_length=1, description="Descripción del envío a zona remota"),
    # Retiro en Persona
    pickup_enabled: bool = Query(True, description="Habilitar retiro en persona"),
    pickup_address: str = Query(..., min_length=1, description="Dirección para retiro en persona"),
    pickup_description: str = Query(..., min_length=1, description="Descripción de la opción de retiro"),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Actualiza los precios de envío, las descripciones y habilita/deshabilita opciones.
    Requiere permisos de administrador.
    """
    try:
        settings_collection = get_collection("shipping_settings")
        settings = await settings_collection.find_one({})
        
        update_data = {
            # Zona Central
            "central_zone_enabled": central_zone_enabled,
            "central_zone_price": central_zone_price,
            "central_zone_description": central_zone_description,
            # Zona Remota
            "remote_zone_enabled": remote_zone_enabled,
            "remote_zone_price": remote_zone_price,
            "remote_zone_description": remote_zone_description,
            # Retiro en Persona
            "pickup_enabled": pickup_enabled,
            "pickup_address": pickup_address,
            "pickup_price": Decimal("0.00"),  # Siempre gratis
            "pickup_description": pickup_description,
            # Metadata
            "updated_at": datetime.now(tz=timezone.utc),
            "updated_by": current_admin_user.user_id
        }
        
        if settings:
            # Actualizar existente
            await settings_collection.update_one(
                {"_id": settings["_id"]},
                {"$set": update_data}
            )
        else:
            # Crear nuevo
            await settings_collection.insert_one(update_data)
        
        enabled_zones = []
        if central_zone_enabled:
            enabled_zones.append(f"Central=${central_zone_price}")
        if remote_zone_enabled:
            enabled_zones.append(f"Remote=${remote_zone_price}")
        if pickup_enabled:
            enabled_zones.append(f"Pickup=GRATIS")
        
        logger.info(
            f"Admin {current_admin_user.username} actualizó configuración de envíos. "
            f"Habilitadas: {', '.join(enabled_zones) if enabled_zones else 'Ninguna'}"
        )
        
        return {
            "message": "Configuración de envíos actualizada correctamente",
            "central_zone_enabled": central_zone_enabled,
            "central_zone_price": central_zone_price,
            "central_zone_description": central_zone_description,
            "remote_zone_enabled": remote_zone_enabled,
            "remote_zone_price": remote_zone_price,
            "remote_zone_description": remote_zone_description,
            "pickup_enabled": pickup_enabled,
            "pickup_address": pickup_address,
            "pickup_price": Decimal("0.00"),
            "pickup_description": pickup_description
        }
    
    except Exception as e:
        logger.error(f"Error al actualizar configuración de envíos: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar la configuración de envíos."
        )

# --- Gestión Masiva de Precios ---

@router.post("/bulk-price-update", tags=["Admin"])
async def bulk_price_update(
    update_data: BulkPriceUpdate,
    products_collection = Depends(get_products_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Actualiza los precios de venta de forma masiva.
    - percentage: ej 0.10 para un aumento del 10%.
    - based_on: 'price' (venta actual) o 'net_price' (costo/neto).
    - target: 'all' o ID de una categoría específica.
    """
    try:
        query = {}
        if update_data.target != "all":
            query["category"] = update_data.target

        # Obtenemos los productos a actualizar.
        # NOTA: esta operación es intencionalmente sin límite — es una acción
        # administrativa masiva. Si el catálogo crece mucho (>10k productos),
        # considerar procesar en batches con un cursor + sleep entre lotes.
        cursor = products_collection.find(query)
        updated_count = 0
        
        async for product_doc in cursor:
            base_value = Decimal("0.00")
            
            if update_data.based_on == "net_price":
                base_value_raw = product_doc.get("net_price")
                if base_value_raw is None:
                    # Si no tiene precio neto, no podemos actualizar basándonos en él
                    continue
                base_value = from_decimal128(base_value_raw)
            else:
                base_value = from_decimal128(product_doc.get("price", Decimal("0.00")))
            
            # Calcular nuevo precio: base * (1 + porcentaje)
            new_price = quantize_money(base_value * (Decimal("1") + update_data.percentage))
            
            # Actualizar en DB
            await products_collection.update_one(
                {"_id": product_doc["_id"]},
                {"$set": decimalize_doc({"price": new_price, "updated_at": datetime.now(tz=timezone.utc)})}
            )
            updated_count += 1
            
        logger.info(f"Admin {current_admin_user.username} realizó una actualización masiva de precios. Productos actualizados: {updated_count}")
        
        return {
            "message": f"Se actualizaron {updated_count} productos correctamente.",
            "updated_count": updated_count
        }
        
    except Exception as e:
        logger.error(f"Error en actualización masiva de precios: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar la actualización masiva de precios."
        )


# --- Endpoints de Configuración del Sistema (Modo Mantenimiento) ---

@router.get("/system-settings", response_model=SystemSettings, tags=["Admin"])
async def get_system_settings(
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Obtiene la configuración global del sistema.
    """
    try:
        settings_collection = get_collection("system_settings")
        settings = await settings_collection.find_one({})
        
        if not settings:
            default_settings = {
                "maintenance_mode": False,
                "maintenance_message": "Estamos realizando mejoras. Volvemos pronto.",
                "allowed_ips": [],
                "updated_at": datetime.now(tz=timezone.utc)
            }
            result = await settings_collection.insert_one(default_settings)
            settings = await settings_collection.find_one({"_id": result.inserted_id})
            
        return SystemSettings(**settings)
        
    except Exception as e:
        logger.error(f"Error al obtener system settings: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener la configuración del sistema."
        )

@router.put("/system-settings", tags=["Admin"])
async def update_system_settings(
    maintenance_mode: bool = Query(..., description="Activar/Desactivar modo mantenimiento"),
    maintenance_message: str = Query(..., min_length=1, description="Mensaje para el usuario"),
    allowed_ips: List[str] = Query([], description="Lista de IPs permitidas"),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    [Admin] Actualiza la configuración global del sistema (ej: Modo Mantenimiento).
    """
    try:
        settings_collection = get_collection("system_settings")
        settings = await settings_collection.find_one({})
        
        update_data = {
            "maintenance_mode": maintenance_mode,
            "maintenance_message": maintenance_message,
            "allowed_ips": allowed_ips,
            "updated_at": datetime.now(tz=timezone.utc),
            "updated_by": current_admin_user.user_id
        }
        
        if settings:
            await settings_collection.update_one(
                {"_id": settings["_id"]},
                {"$set": update_data}
            )
        else:
            await settings_collection.insert_one(update_data)
            
        logger.info(f"Admin {current_admin_user.username} actualizó SYSTEM SETTINGS (Mantenimiento: {maintenance_mode})")
        
        return {
            "message": "Configuración del sistema actualizada correctamente",
            "maintenance_mode": maintenance_mode,
            "maintenance_message": maintenance_message
        }
        
    except Exception as e:
        logger.error(f"Error al actualizar system settings: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar la configuración del sistema."
        )
