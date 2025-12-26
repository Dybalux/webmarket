"""
Script para probar el webhook de Mercado Pago localmente.
Simula una notificación de Mercado Pago para verificar que el backend
procesa correctamente los webhooks.

Uso:
    python scripts/test_webhook.py --order-id <order_id> --payment-status approved
"""

import requests
import argparse
import sys
from datetime import datetime

def test_webhook(base_url: str, order_id: str, payment_status: str = "approved"):
    """
    Simula un webhook de Mercado Pago.
    
    Args:
        base_url: URL base del backend (ej: http://localhost:8000)
        order_id: ID de la orden a actualizar
        payment_status: Estado del pago (approved, rejected, cancelled, in_process)
    """
    
    # Simular el webhook de Mercado Pago
    # Nota: Este es un test simplificado. En producción, MP envía el payment_id
    # y luego el backend consulta la API de MP para obtener los detalles.
    
    webhook_url = f"{base_url}/payments/webhook"
    
    # Parámetros que envía Mercado Pago
    params = {
        "topic": "payment",
        "id": "1234567890"  # ID de pago simulado
    }
    
    print(f"🧪 Probando webhook de Mercado Pago...")
    print(f"📍 URL: {webhook_url}")
    print(f"📦 Order ID: {order_id}")
    print(f"💳 Payment Status: {payment_status}")
    print(f"⏰ Timestamp: {datetime.now().isoformat()}")
    print("-" * 60)
    
    try:
        response = requests.post(webhook_url, params=params)
        
        print(f"\n✅ Respuesta del servidor:")
        print(f"   Status Code: {response.status_code}")
        print(f"   Response: {response.text if response.text else 'Empty'}")
        
        if response.status_code == 200:
            print(f"\n✅ Webhook procesado exitosamente!")
            print(f"\n📝 Próximos pasos:")
            print(f"   1. Verifica los logs del backend")
            print(f"   2. Consulta MongoDB para ver si la orden se actualizó:")
            print(f"      db.orders.findOne({{_id: ObjectId('{order_id}')}})")
            print(f"   3. Verifica la colección de pagos:")
            print(f"      db.payments.find().sort({{date_created: -1}}).limit(1)")
        else:
            print(f"\n❌ Error al procesar webhook")
            
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Error: No se pudo conectar a {base_url}")
        print(f"   Asegúrate de que el backend esté corriendo")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Probar webhook de Mercado Pago")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="URL base del backend (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--order-id",
        required=True,
        help="ID de la orden a actualizar"
    )
    parser.add_argument(
        "--payment-status",
        default="approved",
        choices=["approved", "rejected", "cancelled", "in_process"],
        help="Estado del pago (default: approved)"
    )
    
    args = parser.parse_args()
    
    test_webhook(args.base_url, args.order_id, args.payment_status)

if __name__ == "__main__":
    main()
