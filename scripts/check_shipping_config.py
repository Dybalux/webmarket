"""
Script para verificar la configuración de envíos
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_database, get_collection
from datetime import datetime


async def check_shipping_config():
    """Verifica la configuración actual de envíos"""
    
    print("\n" + "="*60)
    print("🔍 VERIFICACIÓN DE CONFIGURACIÓN DE ENVÍOS")
    print("="*60 + "\n")
    
    db = await get_database()
    settings_collection = get_collection("shipping_settings")
    
    settings = await settings_collection.find_one({})
    
    if not settings:
        print("⚠️  No hay configuración de envíos. Se creará al hacer la primera petición al endpoint.")
        print("\n💡 Configuración por defecto:")
        print("   • Zona Central: $0.00 (GRATIS)")
        print("   • Zona Remota: $1000.00")
        print("   • Retiro: $0.00 (GRATIS)")
        return
    
    print("✅ Configuración encontrada:\n")
    
    print("📍 ZONA CENTRAL (Centro y barrios aledaños)")
    print(f"   Precio: ${settings.get('central_zone_price', 0):.2f}")
    print(f"   Descripción: {settings.get('central_zone_description', 'N/A')}")
    
    if settings.get('central_zone_price', 0) == 0:
        print("   ✅ ENVÍO GRATIS configurado correctamente!")
    else:
        print("   ⚠️  ATENCIÓN: El envío NO está en $0")
    
    print("\n🚛 ZONA REMOTA (Barrios periféricos)")
    print(f"   Precio: ${settings.get('remote_zone_price', 0):.2f}")
    print(f"   Descripción: {settings.get('remote_zone_description', 'N/A')}")
    
    print("\n🏪 RETIRO EN PERSONA")
    print(f"   Precio: ${settings.get('pickup_price', 0):.2f}")
    print(f"   Dirección: {settings.get('pickup_address', 'No configurada')}")
    print(f"   Descripción: {settings.get('pickup_description', 'N/A')}")
    
    if settings.get('pickup_address') in ['', 'Dirección no configurada', 'Configurar dirección en panel de administración']:
        print("   ⚠️  Recuerda configurar la dirección de retiro en el panel de admin")
    
    print("\n📅 Última actualización:")
    updated_at = settings.get('updated_at')
    if updated_at:
        print(f"   {updated_at}")
    
    updated_by = settings.get('updated_by')
    if updated_by:
        print(f"   Por: {updated_by}")
    
    print("\n" + "="*60)
    
    # Verificar productos
    products_collection = get_collection("products")
    total_products = await products_collection.count_documents({})
    avg_price_pipeline = [
        {"$group": {"_id": None, "avg_price": {"$avg": "$price"}}}
    ]
    avg_result = await products_collection.aggregate(avg_price_pipeline).to_list(1)
    avg_price = avg_result[0]["avg_price"] if avg_result else 0
    
    print("\n📦 PRODUCTOS:")
    print(f"   Total: {total_products}")
    print(f"   Precio promedio: ${avg_price:.2f}")
    
    print("\n💡 RECOMENDACIONES:")
    
    if settings.get('central_zone_price', 0) > 0:
        print("   ⚠️  Configurar zona central a $0 para activar envío gratis")
        print("      Usa: PUT /admin/shipping-settings")
    
    if settings.get('pickup_address') in ['', 'Dirección no configurada', 'Configurar dirección en panel de administración']:
        print("   📍 Configurar dirección de retiro en panel admin")
    
    if settings.get('central_zone_price', 0) == 0:
        print("   ✅ Todo listo para ofrecer ENVÍO GRATIS en zona céntrica!")
    
    print("\n" + "="*60 + "\n")


async def show_price_stats():
    """Muestra estadísticas de precios por categoría"""
    
    print("\n" + "="*60)
    print("💰 ESTADÍSTICAS DE PRECIOS POR CATEGORÍA")
    print("="*60 + "\n")
    
    db = await get_database()
    products_collection = get_collection("products")
    
    categories = await products_collection.distinct("category")
    
    for category in sorted(categories):
        pipeline = [
            {"$match": {"category": category}},
            {
                "$group": {
                    "_id": None,
                    "count": {"$sum": 1},
                    "avg_price": {"$avg": "$price"},
                    "min_price": {"$min": "$price"},
                    "max_price": {"$max": "$price"}
                }
            }
        ]
        
        result = await products_collection.aggregate(pipeline).to_list(1)
        
        if result:
            stats = result[0]
            print(f"📊 {category}")
            print(f"   Productos: {stats['count']}")
            print(f"   Precio promedio: ${stats['avg_price']:.2f}")
            print(f"   Rango: ${stats['min_price']:.2f} - ${stats['max_price']:.2f}")
            print()
    
    print("="*60 + "\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Verifica la configuración de envíos")
    parser.add_argument(
        "--show-prices",
        action="store_true",
        help="Muestra estadísticas de precios por categoría"
    )
    
    args = parser.parse_args()
    
    asyncio.run(check_shipping_config())
    
    if args.show_prices:
        asyncio.run(show_price_stats())
