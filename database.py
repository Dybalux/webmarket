import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from config import settings

logger = logging.getLogger(__name__)

class Database:
    client: AsyncIOMotorClient | None = None
    db: AsyncIOMotorDatabase | None = None

db = Database()

async def connect_db():
    """
    Establece la conexión a MongoDB y valida con un ping.
    """
    try:
        db.client = AsyncIOMotorClient(
            settings.DATABASE_URL,
            # Fail fast en vez del default de 20s — si Mongo no está, queremos
            # enterarnos rápido y dejar que el caller (lifespan o scripts)
            # decida qué hacer. En el lifespan se loguea warning y se sigue.
            serverSelectionTimeoutMS=3000,
        )
        db.db = db.client[settings.DATABASE_NAME]
        await db.client.admin.command("ping")
        logger.info(f"✅ Conectado a MongoDB: {settings.DATABASE_URL}/{settings.DATABASE_NAME}")
    except Exception as e:
        logger.error(f"❌ Error al conectar con MongoDB: {e}")
        raise RuntimeError("No se pudo establecer conexión con MongoDB.") from e

async def close_db():
    """
    Cierra la conexión a MongoDB.
    """
    if db.client:
        db.client.close()
        logger.info("🔌 Conexión a MongoDB cerrada.")

def get_collection(collection_name: str):
    """
    Obtiene una colección de la base de datos.
    """
    if db.db is None:  # ✅ Comparación explícita
        raise RuntimeError("La base de datos no está conectada. Asegúrate de llamar a connect_db() en el startup.")
    return db.db[collection_name]

async def get_database() -> AsyncIOMotorDatabase:
    if db.db is None:  # ✅ Comparación segura
        raise RuntimeError("La base de datos no está conectada. Asegúrate de llamar a connect_db() en el startup.")
    return db.db

