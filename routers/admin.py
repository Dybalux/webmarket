from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timedelta

from models import Order, UserResponse, OrderStatus, UserRole, TokenData
from database import get_database, get_collection
from security import get_current_admin_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

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
        total_revenue = total_revenue_result[0]["total"] if total_revenue_result else 0.0
        
        # Ingresos del último mes
        last_month = datetime.utcnow() - timedelta(days=30)
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
        monthly_revenue = monthly_revenue_result[0]["total"] if monthly_revenue_result else 0.0
        
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
                "total": round(total_revenue, 2),
                "last_30_days": round(monthly_revenue, 2)
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
    try:
        # Construir query
        query = {}
        
        if search:
            query["$or"] = [
                {"username": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}}
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
            user = await users_collection.find_one({"_id": ObjectId(order_doc["user_id"])})
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
