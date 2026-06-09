"""
Script para aumentar precios de productos masivamente
Úsalo para ajustar precios antes de implementar la estrategia de envío gratis

Ejemplo de uso:
    # Aumentar todos los productos un 5%
    python scripts/adjust_prices.py --percentage 0.05 --target all
    
    # Aumentar solo cervezas un 3%
    python scripts/adjust_prices.py --percentage 0.03 --target Cerveza
    
    # Aumentar basándose en precio neto (costo) con 20% de markup
    python scripts/adjust_prices.py --percentage 0.20 --target all --based-on net_price
"""

import asyncio
import sys
import argparse
from pathlib import Path

# Agregar el directorio padre al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_database, get_collection
from datetime import datetime, timezone
from bson import ObjectId


async def adjust_prices(percentage: float, target: str = "all", based_on: str = "price", dry_run: bool = False):
    """
    Ajusta los precios de los productos
    
    Args:
        percentage: Porcentaje de ajuste (0.05 = 5%, 0.10 = 10%)
        target: "all" para todos los productos, o nombre de categoría específica
        based_on: "price" (precio actual) o "net_price" (precio costo)
        dry_run: Si es True, solo muestra qué haría sin hacer cambios
    """
    db = await get_database()
    products_collection = get_collection("products")
    
    # Construir query
    query = {}
    if target != "all":
        query["category"] = target
    
    # Obtener productos
    cursor = products_collection.find(query)
    products = await cursor.to_list(length=None)
    
    if not products:
        print(f"❌ No se encontraron productos para el target '{target}'")
        return
    
    print(f"\n{'='*60}")
    print(f"🔧 AJUSTE DE PRECIOS")
    print(f"{'='*60}")
    print(f"📊 Target: {target}")
    print(f"📈 Ajuste: {percentage*100:+.2f}%")
    print(f"📐 Basado en: {based_on}")
    print(f"🔍 Modo: {'SIMULACIÓN (no se guardarán cambios)' if dry_run else 'PRODUCCIÓN (se guardarán cambios)'}")
    print(f"{'='*60}\n")
    
    updated_count = 0
    total_old_price = 0
    total_new_price = 0
    
    for product in products:
        product_id = product["_id"]
        name = product.get("name", "Sin nombre")
        old_price = product.get("price", 0.0)
        
        # Determinar precio base
        if based_on == "net_price":
            base_value = product.get("net_price")
            if base_value is None:
                print(f"⚠️  Saltando '{name}' - no tiene precio neto configurado")
                continue
        else:
            base_value = old_price
        
        # Calcular nuevo precio
        new_price = round(base_value * (1 + percentage), 2)
        
        # Validar que el nuevo precio sea positivo
        if new_price <= 0:
            print(f"⚠️  Saltando '{name}' - nuevo precio inválido: ${new_price}")
            continue
        
        # Mostrar cambio
        change = new_price - old_price
        change_percent = ((new_price / old_price) - 1) * 100 if old_price > 0 else 0
        
        print(f"📦 {name}")
        print(f"   Precio actual: ${old_price:.2f}")
        print(f"   Precio nuevo:  ${new_price:.2f} ({change_percent:+.2f}%)")
        print(f"   Diferencia:    ${change:+.2f}")
        print()
        
        # Actualizar en base de datos (solo si no es dry_run)
        if not dry_run:
            await products_collection.update_one(
                {"_id": product_id},
                {
                    "$set": {
                        "price": new_price,
                        "updated_at": datetime.now(tz=timezone.utc)
                    }
                }
            )
        
        updated_count += 1
        total_old_price += old_price
        total_new_price += new_price
    
    # Resumen
    print(f"\n{'='*60}")
    print(f"📊 RESUMEN")
    print(f"{'='*60}")
    print(f"✅ Productos procesados: {updated_count}")
    print(f"💰 Total precio antiguo: ${total_old_price:.2f}")
    print(f"💵 Total precio nuevo:   ${total_new_price:.2f}")
    print(f"📈 Diferencia total:     ${(total_new_price - total_old_price):+.2f}")
    
    if dry_run:
        print(f"\n🔍 SIMULACIÓN COMPLETADA - No se realizaron cambios")
        print(f"💡 Para aplicar estos cambios, ejecuta sin el flag --dry-run")
    else:
        print(f"\n✅ CAMBIOS GUARDADOS EN LA BASE DE DATOS")
    
    print(f"{'='*60}\n")


async def show_categories():
    """Muestra todas las categorías disponibles"""
    db = await get_database()
    products_collection = get_collection("products")
    
    # Obtener categorías únicas
    categories = await products_collection.distinct("category")
    
    print("\n📋 CATEGORÍAS DISPONIBLES:")
    print("="*40)
    for cat in sorted(categories):
        count = await products_collection.count_documents({"category": cat})
        print(f"  • {cat:<20} ({count} productos)")
    print("="*40 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Ajusta los precios de productos masivamente",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Simular aumento del 5%% en todos los productos
  python scripts/adjust_prices.py --percentage 0.05 --target all --dry-run
  
  # Aumentar cervezas un 3%%
  python scripts/adjust_prices.py --percentage 0.03 --target Cerveza
  
  # Ver categorías disponibles
  python scripts/adjust_prices.py --list-categories
        """
    )
    
    parser.add_argument(
        "--percentage",
        type=float,
        help="Porcentaje de ajuste (ej: 0.05 para 5%%, 0.10 para 10%%)"
    )
    
    parser.add_argument(
        "--target",
        type=str,
        default="all",
        help="Target: 'all' o nombre de categoría específica"
    )
    
    parser.add_argument(
        "--based-on",
        type=str,
        choices=["price", "net_price"],
        default="price",
        help="Basarse en 'price' (precio venta) o 'net_price' (precio costo)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Modo simulación - muestra cambios sin aplicarlos"
    )
    
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="Muestra todas las categorías disponibles"
    )
    
    args = parser.parse_args()
    
    # Mostrar categorías si se solicita
    if args.list_categories:
        asyncio.run(show_categories())
        return
    
    # Validar que se proporcionó percentage
    if args.percentage is None:
        parser.error("Se requiere --percentage excepto cuando se usa --list-categories")
    
    # Ejecutar ajuste
    asyncio.run(adjust_prices(
        percentage=args.percentage,
        target=args.target,
        based_on=args.based_on,
        dry_run=args.dry_run
    ))


if __name__ == "__main__":
    main()
