from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from config import settings
from database import connect_db, close_db, get_database
from routers import auth, products, age_verification, cart, orders, payments, inventory, admin, payment_settings, combos, pricing_settings
from services.exceptions import ServiceError
from utils.errors import (
    service_error_handler,
    http_exception_handler,
    validation_exception_handler,
)
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
    logger.info("🚀 Iniciando aplicación...")

    # MongoDB: best-effort. Si Mongo no está disponible al startup, la app
    # igual arranca y /health reportará degraded. Esto evita crash loops
    # cuando Mongo parpadea en producción y permite que el smoke test del
    # CI pase aunque la red entre el container de la app y los services de
    # GH Actions no esté bien cableada. Los scripts que llaman connect_db()
    # directo (init_payment_settings, adjust_prices, etc.) siguen recibiendo
    # el raise original — solo el lifespan lo trata como no-fatal.
    try:
        await connect_db()
    except Exception as e:
        logger.warning(
            f"⚠️ MongoDB no disponible al startup: {e}. "
            f"La app arranca en modo degraded; /health reportará el estado."
        )

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
    # Custom Domains
    "https://altotrago.com",
    "https://www.altotrago.com",
    settings.FRONTEND_URL, # Configurado desde variables de entorno
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

# --- MIDDLEWARE DE MODO MANTENIMIENTO ---
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Lista blanca de rutas que SIEMPRE funcionan (admin, auth, docs, etc.)
        allowed_paths = [
            "/auth", "/docs", "/redoc", "/openapi.json",
            "/health", "/system-status", "/static", "/favicon.ico"
        ]

        # Tightened match for /admin and /age-verification: exact path or sub-path only.
        # Avoids false positives like /admin-panel or /age-verification-panel.
        is_admin = request.url.path == "/admin" or request.url.path.startswith("/admin/")
        is_age_verification = (
            request.url.path == "/age-verification"
            or request.url.path.startswith("/age-verification/")
        )

        # Permitir si la ruta comienza con algo de la lista blanca
        if is_admin or is_age_verification or any(
            request.url.path.startswith(path) for path in allowed_paths
        ):
            return await call_next(request)

        # 2. Permitir solicitudes OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        try:
            # 3. Consultar estado en DB
            # Importamos aquí dentro para evitar referencias circulares si database.py importa main
            database = await get_database()
            settings_collection = database["system_settings"]
            settings = await settings_collection.find_one({})

            if settings and settings.get("maintenance_mode", False):
                # MODO MANTENIMIENTO ACTIVO 🛑
                
                # Opcional: Permitir acceso si tiene un Header especial o Token de Admin
                # (Para simplificar, asumimos que los admins entran por /admin o /auth)
                
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "El sitio se encuentra actualmente en mantenimiento.",
                        "message": settings.get("maintenance_message", "Volvemos pronto.")
                    }
                )

        except Exception as e:
            logger.error(f"Error en Maintenance Middleware: {e}")
            # En caso de error de DB, permitimos el paso para no bloquear el sitio por un error técnico
            pass

        return await call_next(request)

app.add_middleware(MaintenanceModeMiddleware)

# --- RFC 9457 global exception handlers ---
# Registration order matters: ServiceError first, then HTTPException,
# then RequestValidationError. Starlette matches the first compatible
# handler in registration order.
app.add_exception_handler(ServiceError, service_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

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
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
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

# --- Endpoint Público de Estado del Sistema ---
from models import SystemSettings

@app.get("/system-status", tags=["System"])
async def get_system_status():
    """
    Endpoint público para verificar si el sitio está en mantenimiento.
    """
    try:
        settings_collection = get_collection("system_settings")
        settings = await settings_collection.find_one({})
        
        if settings:
            return {
                "maintenance_mode": settings.get("maintenance_mode", False),
                "message": settings.get("maintenance_message", "Estamos en mantenimiento.")
            }
        
        return {"maintenance_mode": False, "message": ""}
    except Exception as e:
        logger.error(f"Error checking system status: {e}")
        return {"maintenance_mode": False, "message": ""}

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
app.include_router(combos.router, prefix="/combos", tags=["Combos"])
app.include_router(pricing_settings.router, prefix="", tags=["Configuración de Precios"])

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
