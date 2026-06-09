"""
Script para inicializar la configuración de pagos con valores por defecto.
Ejecutar una sola vez después de crear la base de datos.
"""
import asyncio
import sys
from pathlib import Path

# Agregar el directorio raíz al path para importar módulos
sys.path.append(str(Path(__file__).parent.parent))

from database import connect_db, close_db, get_collection
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_payment_settings():
    """Inicializa la configuración de pagos con valores por defecto."""
    try:
        # Conectar a la base de datos
        await connect_db()
        logger.info("✅ Conectado a MongoDB")
        
        # Obtener la colección
        payment_settings_collection = get_collection("payment_settings")
        
        # Verificar si ya existe configuración
        existing = await payment_settings_collection.find_one({})
        
        if existing:
            logger.warning("⚠️ Ya existe configuración de pagos. No se realizarán cambios.")
            logger.info(f"Configuración actual:")
            logger.info(f"  - Alias: {existing.get('transfer_alias')}")
            logger.info(f"  - WhatsApp: {existing.get('transfer_whatsapp')}")
            return
        
        # Crear configuración por defecto
        default_settings = {
            "transfer_alias": "TU.ALIAS",
            "transfer_whatsapp": "TU.WHATSAPP",
            "updated_at": datetime.now(tz=timezone.utc),
            "updated_by": None  # Inicialización automática
        }
        
        result = await payment_settings_collection.insert_one(default_settings)
        
        logger.info("✅ Configuración de pagos inicializada correctamente")
        logger.info(f"  - ID: {result.inserted_id}")
        logger.info(f"  - Alias: {default_settings['transfer_alias']}")
        logger.info(f"  - WhatsApp: {default_settings['transfer_whatsapp']}")
        logger.info("")
        logger.info("💡 Puedes actualizar estos valores desde el panel de admin usando:")
        logger.info("   PUT /api/admin/payment-settings")
        
    except Exception as e:
        logger.error(f"❌ Error al inicializar configuración de pagos: {e}", exc_info=True)
        raise
    finally:
        await close_db()
        logger.info("🔴 Desconectado de MongoDB")


if __name__ == "__main__":
    logger.info("🚀 Iniciando script de inicialización de configuración de pagos...")
    asyncio.run(init_payment_settings())
    logger.info("✅ Script completado")
