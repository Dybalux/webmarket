"""
Script para probar el envío de emails.
Ejecutar: py scripts/test_email.py
"""
import asyncio
import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.append(str(Path(__file__).parent.parent))

from email_service import send_new_order_notification
from config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_email():
    """Prueba el envío de email de notificación."""
    logger.info("🧪 Probando envío de email...")
    
    # Verificar configuración
    if not settings.EMAIL_ENABLED:
        logger.warning("⚠️ EMAIL_ENABLED está en False. Cambia a True en el .env para probar el envío real.")
    
    if not settings.ADMIN_EMAIL:
        logger.error("❌ ADMIN_EMAIL no está configurado en el .env")
        return
    
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.error("❌ SMTP_USER o SMTP_PASSWORD no están configurados en el .env")
        return
    
    logger.info(f"📧 Configuración:")
    logger.info(f"  - Admin Email: {settings.ADMIN_EMAIL}")
    logger.info(f"  - SMTP Host: {settings.SMTP_HOST}:{settings.SMTP_PORT}")
    logger.info(f"  - SMTP User: {settings.SMTP_USER}")
    logger.info(f"  - Email Enabled: {settings.EMAIL_ENABLED}")
    
    # Enviar email de prueba
    await send_new_order_notification(
        order_id="TEST-12345",
        user_email="cliente-prueba@example.com",
        total_amount=15750.50,
        payment_method="Transferencia Bancaria"
    )
    
    logger.info("✅ Prueba completada. Revisa tu email si EMAIL_ENABLED=true")


if __name__ == "__main__":
    logger.info("🚀 Iniciando prueba de email...")
    asyncio.run(test_email())
    logger.info("✅ Script completado")
