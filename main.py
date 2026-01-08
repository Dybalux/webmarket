from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from database import connect_db, close_db, get_database
from routers import auth, products, age_verification, cart, orders, payments, inventory, admin, payment_settings
from contextlib import asynccontextmanager
from datetime import datetime
import uvicorn
import logging
import os
import redis.asyncio as redis
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Iniciando aplicación. Conectando a MongoDB...")
    await connect_db()

    # Conexión a Redis para el Rate Limiter
    try:
        redis_connection = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        await FastAPILimiter.init(redis_connection)
        logger.info("✅ Conectado a Redis y FastAPILimiter inicializado.")
    except Exception as e:
        logger.error(f"❌ No se pudo conectar a Redis o inicializar FastAPILimiter: {e}")

    yield  # ⏳ Aquí corre la app

    logger.info("🔴 Cerrando aplicación. Desconectando de MongoDB...")
    await close_db()

app = FastAPI(
    title="EscabiAPI",
    description="API para gestionar productos, pedidos, carritos, autenticación y pagos de usuarios",
    version="0.0.1",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

#Middleware
# --- CONFIGURACIÓN DE CORS ---
# Lista de orígenes permitidos. En producción, deberías poner aquí el dominio de tu frontend.
# Ejemplo: ["https://www.mitienda.com", "https://mitienda.com"]
origins = [
    "http://localhost:3000",  # Origen común para React en desarrollo
    "http://localhost:5173",  # Vite default port (React/Vue)
    "http://localhost:8080",  # Origen común para Vue en desarrollo
    "http://localhost:4200",  # Origen común para Angular en desarrollo
    # Vercel - deployment URLs
    "https://escabi-frontend-3dtk1loe5-dybaluxs-projects.vercel.app",  # Current Vercel deployment
    "https://escabi-frontend.vercel.app",  # Production Vercel (if you set up custom domain)
]

# En producción, NUNCA usar "*"
if settings.ENV.lower() == "development":
    # En desarrollo, permitir todos los orígenes
    origins.append("*")
else:
    # En producción, solo permitir orígenes específicos
    # Agregar aquí cualquier dominio adicional de producción
    pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True, # Permite cookies y encabezados de autorización
    allow_methods=["*"],    # Permite todos los métodos (GET, POST, etc.)
    allow_headers=["*"],    # Permite todos los encabezados
)

# Rutas principales

# Health Check Endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """
    Endpoint de health check para verificar el estado de la API.
    Verifica la conexión a MongoDB y Redis.
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "EscabiAPI",
        "version": "0.0.1",
        "checks": {}
    }
    
    # Verificar MongoDB
    try:
        database = await get_database()
        # Hacer un ping simple a la base de datos
        await database.command("ping")
        health_status["checks"]["mongodb"] = {
            "status": "up",
            "message": "Conexión exitosa"
        }
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["mongodb"] = {
            "status": "down",
            "message": f"Error de conexión: {str(e)}"
        }
        logger.error(f"Health check - MongoDB error: {e}")
    
    # Verificar Redis (opcional, puede no estar disponible en desarrollo)
    try:
        # Intentar hacer ping a Redis si está configurado
        redis_connection = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        await redis_connection.ping()
        await redis_connection.close()
        health_status["checks"]["redis"] = {
            "status": "up",
            "message": "Conexión exitosa"
        }
    except Exception as e:
        # Redis es opcional, no marca la API como unhealthy
        health_status["checks"]["redis"] = {
            "status": "down",
            "message": f"No disponible: {str(e)}"
        }
        logger.warning(f"Health check - Redis no disponible: {e}")
    
    return health_status

# Montar rutas
app.include_router(products.router, prefix="/products", tags=["Productos"])
app.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
app.include_router(age_verification.router, prefix="/age-verification", tags=["Verificación de Edad"])
app.include_router(cart.router, prefix="/cart", tags=["Carrito de Compras"])
app.include_router(orders.router, prefix="/orders", tags=["Pedidos"])
app.include_router(payments.router, prefix="/payments", tags=["Pagos"])
app.include_router(inventory.router, prefix="/inventory", tags=["Inventario"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(payment_settings.router, prefix="", tags=["Configuración de Pagos"])

# Punto de entrada
if __name__ == "__main__":
    import os
    logger.info(f"🌍 Ambiente: {settings.ENV}")

    #Railway provee la variable PORT
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"🚀 Iniciando servidor en puerto {port}")

    # En desarollo con recarga asutomática, en producción sin recarga
    if(settings.ENV.lower() == "development"):
        uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
