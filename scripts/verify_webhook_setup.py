"""
Script para verificar que el webhook de Mercado Pago está configurado correctamente.
Verifica la base de datos y muestra estadísticas de webhooks recibidos.

Uso:
    python scripts/verify_webhook_setup.py
"""

import asyncio
import sys
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta
from bson import ObjectId
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

async def verify_webhook_setup():
    """Verifica la configuración del webhook y muestra estadísticas."""
    
    # Conectar a MongoDB
    database_url = os.getenv("DATABASE_URL")
    database_name = os.getenv("DATABASE_NAME")
    
    if not database_url or not database_name:
        print("❌ Error: DATABASE_URL o DATABASE_NAME no están configurados en .env")
        sys.exit(1)
    
    print(f"🔌 Conectando a MongoDB...")
    client = AsyncIOMotorClient(database_url)
    db = client[database_name]
    
    try:
        # Verificar conexión
        await db.command("ping")
        print(f"✅ Conectado a MongoDB: {database_name}\n")
        
        # 1. Verificar colecciones
        print("📊 Verificando colecciones...")
        collections = await db.list_collection_names()
        
        required_collections = ["orders", "payments"]
        for coll in required_collections:
            if coll in collections:
                count = await db[coll].count_documents({})
                print(f"   ✅ {coll}: {count} documentos")
            else:
                print(f"   ⚠️  {coll}: No existe")
        
        print()
        
        # 2. Verificar órdenes recientes
        print("📦 Órdenes recientes (últimas 5):")
        orders_cursor = db.orders.find().sort("created_at", -1).limit(5)
        orders = await orders_cursor.to_list(length=5)
        
        if orders:
            for order in orders:
                order_id = str(order["_id"])
                status = order.get("status", "N/A")
                payment_id = order.get("payment_id", "Sin pago")
                created_at = order.get("created_at", "N/A")
                total = order.get("total_amount", 0)
                
                print(f"\n   Order ID: {order_id}")
                print(f"   Estado: {status}")
                print(f"   Payment ID: {payment_id}")
                print(f"   Total: ${total}")
                print(f"   Creada: {created_at}")
        else:
            print("   ⚠️  No hay órdenes en la base de datos")
        
        print()
        
        # 3. Verificar pagos recibidos
        print("💳 Pagos recibidos (últimos 5):")
        payments_cursor = db.payments.find().sort("date_created", -1).limit(5)
        payments = await payments_cursor.to_list(length=5)
        
        if payments:
            for payment in payments:
                payment_id = payment.get("id", "N/A")
                status = payment.get("status", "N/A")
                external_ref = payment.get("external_reference", "N/A")
                amount = payment.get("transaction_amount", 0)
                date_created = payment.get("date_created", "N/A")
                
                print(f"\n   Payment ID: {payment_id}")
                print(f"   Estado: {status}")
                print(f"   Order ID (external_reference): {external_ref}")
                print(f"   Monto: ${amount}")
                print(f"   Fecha: {date_created}")
        else:
            print("   ⚠️  No hay pagos registrados")
            print("   💡 Esto significa que el webhook aún no ha recibido notificaciones")
        
        print()
        
        # 4. Verificar órdenes con pago
        print("🔗 Órdenes con pago asociado:")
        orders_with_payment = await db.orders.count_documents({"payment_id": {"$exists": True}})
        total_orders = await db.orders.count_documents({})
        
        if total_orders > 0:
            percentage = (orders_with_payment / total_orders) * 100
            print(f"   {orders_with_payment} de {total_orders} órdenes ({percentage:.1f}%)")
        else:
            print("   ⚠️  No hay órdenes en la base de datos")
        
        print()
        
        # 5. Estadísticas por estado de orden
        print("📈 Estadísticas por estado de orden:")
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        stats = await db.orders.aggregate(pipeline).to_list(length=None)
        
        if stats:
            for stat in stats:
                status = stat["_id"]
                count = stat["count"]
                print(f"   {status}: {count}")
        else:
            print("   ⚠️  No hay datos")
        
        print()
        
        # 6. Verificar webhooks duplicados
        print("🔍 Verificando webhooks duplicados:")
        pipeline = [
            {"$group": {"_id": "$id", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
            {"$sort": {"count": -1}}
        ]
        duplicates = await db.payments.aggregate(pipeline).to_list(length=None)
        
        if duplicates:
            print(f"   ⚠️  Se encontraron {len(duplicates)} pagos con webhooks duplicados:")
            for dup in duplicates[:5]:  # Mostrar solo los primeros 5
                print(f"      Payment ID {dup['_id']}: {dup['count']} webhooks")
        else:
            print("   ✅ No hay webhooks duplicados")
        
        print()
        
        # 7. Recomendaciones
        print("💡 Recomendaciones:")
        
        if not payments:
            print("   • Realiza una compra de prueba para verificar el webhook")
            print("   • Asegúrate de que la URL del webhook esté configurada en Mercado Pago")
        
        if duplicates:
            print("   • Implementa validación de idempotencia para evitar procesar webhooks duplicados")
        
        if orders_with_payment < total_orders:
            print("   • Algunas órdenes no tienen payment_id asociado")
            print("   • Verifica que el webhook esté actualizando correctamente las órdenes")
        
        print()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    finally:
        client.close()
        print("🔌 Conexión cerrada")

if __name__ == "__main__":
    asyncio.run(verify_webhook_setup())
