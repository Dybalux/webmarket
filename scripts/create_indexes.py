"""
Script para crear índices en MongoDB para mejorar el rendimiento de las consultas.
Ejecutar este script una vez después del deployment inicial o cuando se actualice la estructura de índices.

Uso:
    python scripts/create_indexes.py
"""

import asyncio
import sys
import os

# Agregar el directorio raíz al path para importar módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def create_indexes():
    """Crea todos los índices necesarios en las colecciones de MongoDB."""
    
    logger.info("🔗 Conectando a MongoDB...")
    client = AsyncIOMotorClient(settings.DATABASE_URL)
    db = client[settings.DATABASE_NAME]
    
    try:
        # Verificar conexión
        await client.admin.command('ping')
        logger.info("✅ Conectado a MongoDB exitosamente")
        
        # ==================== ÍNDICES PARA USERS ====================
        logger.info("📊 Creando índices para colección 'users'...")
        users_collection = db.users
        
        # Índice único en email
        await users_collection.create_index("email", unique=True, name="idx_users_email")
        logger.info("  ✓ Índice único creado en users.email")
        
        # Índice único en username
        await users_collection.create_index("username", unique=True, name="idx_users_username")
        logger.info("  ✓ Índice único creado en users.username")
        
        # Índice en role para filtrado de admins
        await users_collection.create_index("role", name="idx_users_role")
        logger.info("  ✓ Índice creado en users.role")
        
        # Índice en age_verified para consultas de verificación
        await users_collection.create_index("age_verified", name="idx_users_age_verified")
        logger.info("  ✓ Índice creado en users.age_verified")
        
        # ==================== ÍNDICES PARA PRODUCTS ====================
        logger.info("📊 Creando índices para colección 'products'...")
        products_collection = db.products
        
        # Índice en category para filtrado
        await products_collection.create_index("category", name="idx_products_category")
        logger.info("  ✓ Índice creado en products.category")
        
        # Índice en stock para consultas de disponibilidad
        await products_collection.create_index("stock", name="idx_products_stock")
        logger.info("  ✓ Índice creado en products.stock")
        
        # Índice de texto para búsqueda por nombre y descripción
        await products_collection.create_index(
            [("name", "text"), ("description", "text")],
            name="idx_products_text_search"
        )
        logger.info("  ✓ Índice de texto creado en products.name y products.description")
        
        # Índice compuesto para ordenamiento por precio
        await products_collection.create_index(
            [("category", 1), ("price", 1)],
            name="idx_products_category_price"
        )
        logger.info("  ✓ Índice compuesto creado en products.category + products.price")
        
        # ==================== ÍNDICES PARA CARTS ====================
        logger.info("📊 Creando índices para colección 'carts'...")
        carts_collection = db.carts
        
        # Índice único en user_id (un carrito por usuario)
        await carts_collection.create_index("user_id", unique=True, name="idx_carts_user_id")
        logger.info("  ✓ Índice único creado en carts.user_id")
        
        # ==================== ÍNDICES PARA ORDERS ====================
        logger.info("📊 Creando índices para colección 'orders'...")
        orders_collection = db.orders
        
        # Índice en user_id para consultas de órdenes por usuario
        await orders_collection.create_index("user_id", name="idx_orders_user_id")
        logger.info("  ✓ Índice creado en orders.user_id")
        
        # Índice en status para filtrado por estado
        await orders_collection.create_index("status", name="idx_orders_status")
        logger.info("  ✓ Índice creado en orders.status")
        
        # Índice compuesto para consultas de órdenes por usuario y estado
        await orders_collection.create_index(
            [("user_id", 1), ("status", 1)],
            name="idx_orders_user_status"
        )
        logger.info("  ✓ Índice compuesto creado en orders.user_id + orders.status")
        
        # Índice en created_at para ordenamiento por fecha
        await orders_collection.create_index(
            "created_at",
            name="idx_orders_created_at"
        )
        logger.info("  ✓ Índice creado en orders.created_at")
        
        # Índice compuesto para paginación eficiente
        await orders_collection.create_index(
            [("created_at", -1), ("_id", -1)],
            name="idx_orders_pagination"
        )
        logger.info("  ✓ Índice de paginación creado en orders.created_at + orders._id")
        
        # ==================== ÍNDICES PARA PAYMENTS ====================
        logger.info("📊 Creando índices para colección 'payments'...")
        payments_collection = db.payments
        
        # Índice en order_id para búsqueda rápida de pagos por orden
        await payments_collection.create_index("order_id", name="idx_payments_order_id")
        logger.info("  ✓ Índice creado en payments.order_id")
        
        # Índice en user_id para historial de pagos del usuario
        await payments_collection.create_index("user_id", name="idx_payments_user_id")
        logger.info("  ✓ Índice creado en payments.user_id")
        
        # Índice en status para filtrado
        await payments_collection.create_index("status", name="idx_payments_status")
        logger.info("  ✓ Índice creado en payments.status")
        
        # ==================== ÍNDICES PARA REFRESH_TOKENS ====================
        logger.info("📊 Creando índices para colección 'refresh_tokens'...")
        refresh_tokens_collection = db.refresh_tokens
        
        # Índice único en token
        await refresh_tokens_collection.create_index("token", unique=True, name="idx_refresh_tokens_token")
        logger.info("  ✓ Índice único creado en refresh_tokens.token")
        
        # Índice en user_id para búsqueda de tokens por usuario
        await refresh_tokens_collection.create_index("user_id", name="idx_refresh_tokens_user_id")
        logger.info("  ✓ Índice creado en refresh_tokens.user_id")
        
        # Índice TTL para expiración automática de tokens
        await refresh_tokens_collection.create_index(
            "expires_at",
            expireAfterSeconds=0,
            name="idx_refresh_tokens_ttl"
        )
        logger.info("  ✓ Índice TTL creado en refresh_tokens.expires_at")
        
        # ==================== RESUMEN ====================
        logger.info("\n" + "="*60)
        logger.info("✅ TODOS LOS ÍNDICES CREADOS EXITOSAMENTE")
        logger.info("="*60)
        
        # Listar todos los índices creados
        logger.info("\n📋 Resumen de índices por colección:")
        
        for collection_name in ["users", "products", "carts", "orders", "payments", "refresh_tokens"]:
            collection = db[collection_name]
            indexes = await collection.index_information()
            logger.info(f"\n  {collection_name}:")
            for idx_name, idx_info in indexes.items():
                if idx_name != "_id_":  # Omitir el índice por defecto
                    logger.info(f"    - {idx_name}: {idx_info.get('key', [])}")
        
        logger.info("\n" + "="*60)
        
    except Exception as e:
        logger.error(f"❌ Error al crear índices: {e}")
        raise
    finally:
        client.close()
        logger.info("🔌 Conexión cerrada")

if __name__ == "__main__":
    logger.info("🚀 Iniciando creación de índices de MongoDB...")
    asyncio.run(create_indexes())
    logger.info("✅ Proceso completado")
