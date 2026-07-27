from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional

class Settings(BaseSettings):
    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # Refresh tokens duran 7 días por defecto

    # MongoDB
    DATABASE_URL: str
    DATABASE_NAME: str

    # --- NUEVA VARIABLE PARA REDIS ---
    REDIS_URL: str = "redis://localhost:6379"

    # --- NUEVAS VARIABLES PARA MERCADO PAGO ---
    # Tu Access Token privado de Mercado Pago (lo leerá del .env)
    MERCADOPAGO_ACCESS_TOKEN: Optional[str] = None
    MERCADOPAGO_PUBLIC_KEY: Optional[str] = None
    MERCADOPAGO_WEBHOOK_SECRET: Optional[str] = None  # Para validar firma de webhooks
    MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS: bool = False  # Solo desarrollo: permite webhooks sin firma
    
    # URL base para tus webhooks (importante para desarrollo y producción)
    # En desarrollo apuntamos al Cloudflare Tunnel local, en producción será tu dominio
    WEBHOOK_BASE_URL: str = "http://localhost:8000"
    
    # URL del frontend para redirecciones después del pago
    FRONTEND_URL: str = "http://localhost:3000"

    # --- CONFIGURACIÓN DE EMAIL (Resend) ---
    # Resend API para enviar notificaciones a admins
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: Optional[str] = None  # Email del remitente
    EMAIL_ENABLED: bool = False  # Activar/desactivar emails

    # Auth hardening
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_LOCKOUT_SECONDS: int = 900

    # Entorno
    ENV: str = "development"

    @field_validator("ENV")
    def validate_env(cls, v):
        allowed = {"development", "production", "test"}
        if v not in allowed:
            raise ValueError(f"ENV debe ser uno de: {allowed}")
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="allow"
    )

settings = Settings()
