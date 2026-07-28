from bson import ObjectId
from pydantic import ConfigDict, BaseModel, Field, EmailStr, field_validator
from pydantic_core import core_schema
from typing import List, Optional, Any
from datetime import datetime, timezone
from pydantic.json_schema import JsonSchemaValue
import enum
import re

from utils.money import Money
from decimal import Decimal

class PyObjectId(ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        return core_schema.union_schema(
            [
                core_schema.is_instance_schema(ObjectId),
                core_schema.str_schema(),
            ],
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: str(x),  # convierte ObjectId a str al serializar
                when_used="always"
            )
        )
    
    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: core_schema.CoreSchema, handler
    ) -> JsonSchemaValue:
        # Esquema para documentación OpenAPI
        return {'type': 'string', 'example': '507f1f77bcf86cd799439011'}
    
    @classmethod
    def validate(cls, value):
        if isinstance(value, ObjectId):
            return value
        if isinstance(value, str):
            try:
                return ObjectId(value)
            except Exception:
                raise ValueError("Invalid ObjectId string")
        raise TypeError("ObjectId must be a string or ObjectId instance")
    
# --- Enumeraciones para mejorar la legibilidad y validación ---
# --- Base for request models with strict validation ---
class BaseRequestModel(BaseModel):
    """Base for all incoming request models.

    ``extra="forbid"`` rejects any payload fields not declared on the model,
    returning a 422 (via FastAPI's RFC 9457 handler) instead of silently
    ignoring unexpected data.
    """
    model_config = ConfigDict(extra="forbid")


class ProductCategory(str, enum.Enum):
    BEER = "Cerveza"
    WINE_RED = "Vino Tinto"
    WINE_WHITE = "Vino Blanco"
    WINE_ROSE = "Vino Rosado"
    SPIRITS_WHISKY = "Whisky"
    SPIRITS_VODKA = "Vodka"
    SPIRITS_GIN = "Gin"
    SPIRITS_RUM = "Ron"
    SPIRITS_TEQUILA = "Tequila"
    SPIRITS_FERNET = "Fernet"
    SOFT_DRINK = "Gaseosa" 
    OTHER = "Otro"

class UserRole(str, enum.Enum):
    CUSTOMER = "customer"
    ADMIN = "admin"

class OrderStatus(str, enum.Enum):
    PENDING = "Pendiente"
    PROCESSING = "En Proceso"
    SHIPPED = "Enviado"
    DELIVERED = "Entregado"
    CANCELLED = "Cancelado"
    REFUNDED = "Reembolsado"

class PaymentStatus(str, enum.Enum):
    PENDING = "Pendiente"
    COMPLETED = "Completado"
    FAILED = "Fallido"
    REFUNDED = "Reembolsado"
    CANCELED = "Cancelado"

class PaymentMethod(str, enum.Enum):
    MERCADO_PAGO = "Mercado Pago"
    TRANSFERENCIA = "Transferencia Bancaria"

# --- Modelos de Datos Principales ---

# Modelo para un Producto (Bebida)
class Product(BaseModel):
    # id se generará en la DB, por eso es Optional y str para MongoDB ObjectId
    id: Optional[PyObjectId] = Field(default=None, alias="_id", serialization_alias="id",exclude=False)
    name: str = Field(..., min_length=3, max_length=100, description="Nombre de la bebida")
    description: Optional[str] = Field(None, max_length=500, description="Descripción detallada del producto")
    price: Money = Field(..., gt=0, description="Precio de venta (mayor que cero)")
    category: ProductCategory = Field(..., description="Categoría de la bebida")
    stock: int = Field(..., ge=0, description="Cantidad disponible en inventario (mayor o igual a cero)")
    image_url: Optional[str] = Field(None, description="URL de la imagen principal del producto")
    abv: Optional[float] = Field(None, ge=0, le=100, description="Grado alcohólico por volumen (Alcohol by Volume), 0-100%")  # Not money — stays float
    volume_ml: Optional[int] = Field(None, gt=0, description="Volumen del envase en mililitros")
    origin: Optional[str] = Field(None, max_length=50, description="País o región de origen")
    net_price: Optional[Money] = Field(None, ge=0, description="Precio de costo o neto del producto", exclude=True)
    active: bool = Field(default=True, description="Indica si el producto está habilitado para venta")
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True
    )

class AdminProduct(Product):
    """Versión extendida del producto para administradores que incluye el precio neto"""
    net_price: Optional[Money] = Field(None, ge=0, description="Precio de costo o neto (Visible solo para admin)", exclude=False)

class ProductUpdate(BaseRequestModel):
    """Modelo para actualizar un producto, permite campos opcionales y cálculo por ganancia"""
    name: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    price: Optional[Money] = Field(None, gt=0)
    category: Optional[ProductCategory] = None
    stock: Optional[int] = Field(None, ge=0)
    image_url: Optional[str] = None
    abv: Optional[float] = Field(None, ge=0, le=100)  # Not money — stays float
    volume_ml: Optional[int] = Field(None, gt=0)
    origin: Optional[str] = Field(None, max_length=50)
    net_price: Optional[Money] = Field(None, ge=0)
    active: Optional[bool] = None
    profit_percentage: Optional[float] = Field(None, description="Porcentaje de ganancia para calcular el precio automáticamente")  # Not money — stays float

    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True,
    )


# Common passwords blocklist for password policy (F-009)
COMMON_PASSWORDS: frozenset[str] = frozenset({
    "password", "123456", "123456789", "12345678", "1234567890",
    "qwerty", "abc123", "monkey", "master", "dragon",
    "111111", "baseball", "iloveyou", "trustno1", "sunshine",
    "princess", "football", "charlie", "shadow", "michael",
    "password1", "password123", "admin", "letmein", "welcome",
    "login", "qwerty123", "1234567", "12345", "12345678910",
    "password1234", "password12345", "qwerty123456",
})


# Modelos para Usuarios
class UserRegister(BaseRequestModel):
    username: str = Field(..., min_length=3, max_length=50, description="Nombre de usuario único")
    email: EmailStr = Field(..., description="Correo electrónico válido")
    password: str = Field(..., min_length=12, description="Contraseña segura (mínimo 12 caracteres)")
    birth_date: datetime = Field(..., description="Fecha de nacimiento para verificación de edad")

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters long")
        if v.lower() in COMMON_PASSWORDS:
            raise ValueError("Password is too common — choose a more unique password")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\\/~`';]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class UserLogin(BaseRequestModel):
    email_or_username: str = Field(..., description="Nombre de usuario o correo electrónico")
    password: str = Field(..., description="Contraseña")

class UserResponse(BaseModel):
    id: PyObjectId = Field(alias="_id")
    username: str
    email: EmailStr
    role: UserRole = UserRole.CUSTOMER # Por defecto, los nuevos usuarios son clientes
    age_verified: bool = False # Se actualizará después de la verificación
    birth_date: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True,
    )


# Modelos para la Autenticación JWT
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenResponse(BaseModel):
    """Respuesta completa de autenticación con access y refresh tokens"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Segundos hasta expiración del access token

class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[str] = None
    roles: List[UserRole] = []
    age_verified: bool = False # Para pasar en el token la verificación de edad

class RefreshToken(BaseModel):
    """Modelo para almacenar refresh tokens en la base de datos"""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    token: str = Field(..., description="El refresh token hasheado")
    user_id: str = Field(..., description="ID del usuario propietario del token")
    expires_at: datetime = Field(..., description="Fecha de expiración del refresh token")
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    revoked: bool = Field(default=False, description="Si el token ha sido revocado")
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True,
    )

class AgeVerificationResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# Password reset schemas (F-015)
class ForgotPasswordRequest(BaseRequestModel):
    email: EmailStr = Field(..., description="Email address for password reset")


class PasswordResetConfirm(BaseRequestModel):
    token: str = Field(..., description="Password reset token from email")
    new_password: str = Field(..., min_length=12, description="New password (must meet policy)")

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters long")
        if v.lower() in COMMON_PASSWORDS:
            raise ValueError("Password is too common — choose a more unique password")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\\/~`';]", v):
            raise ValueError("Password must contain at least one special character")
        return v

# Modelos para Paginación
class PaginationMeta(BaseModel):
    """Metadatos de paginación"""
    total: int = Field(..., description="Total de items disponibles")
    page: int = Field(..., description="Página actual (1-indexed)")
    page_size: int = Field(..., description="Tamaño de página")
    total_pages: int = Field(..., description="Total de páginas")
    has_next: bool = Field(..., description="Si existe página siguiente")
    has_prev: bool = Field(..., description="Si existe página anterior")

class PaginatedResponse(BaseModel):
    """Respuesta paginada genérica"""
    items: List[Any] = Field(..., description="Items de la página actual")
    meta: PaginationMeta = Field(..., description="Metadatos de paginación")


# Modelos para Carrito de Compras
class CartItem(BaseRequestModel):
    product_id: str = Field(..., description="ID del producto o combo en el carrito")
    quantity: int = Field(..., gt=0, description="Cantidad del producto/combo (mayor que cero)")

class Cart(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    user_id: str = Field(..., description="ID del usuario propietario del carrito")
    items: List[CartItem] = [] # Lista de productos en el carrito
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str},
    }

# Modelos para respuesta enriquecida del carrito
class CartItemDetailed(BaseModel):
    """Item del carrito con información detallada del producto o combo"""
    product_id: str = Field(..., description="ID del producto o combo")
    quantity: int = Field(..., description="Cantidad en el carrito")
    item_type: str = Field(..., description="Tipo de item: 'product' o 'combo'")
    name: str = Field(..., description="Nombre del producto o combo")
    price: Money = Field(..., description="Precio unitario")
    image_url: Optional[str] = Field(None, description="URL de la imagen")
    stock: Optional[int] = Field(None, description="Stock disponible (solo para productos)")
    combo_items: Optional[List[dict]] = Field(None, description="Items del combo (solo para combos)")

class CartDetailed(BaseModel):
    """Carrito con información detallada de productos y combos"""
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    items: List[CartItemDetailed]
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str},
    }

# Modelos para Pedidos
class OrderItem(BaseModel):
    _id: Optional[PyObjectId] = None
    product_id: PyObjectId  = Field(..., description="ID del producto")
    name: str = Field(..., description="Nombre del producto al momento de la compra")
    quantity: int = Field(..., gt=0, description="Cantidad del producto")
    price_at_purchase: Money = Field(..., gt=0, description="Precio unitario del producto al momento de la compra")
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True,
    )

class Address(BaseRequestModel):
    street: str
    city: str
    state: str
    zip_code: str
    country: str
    
class OrderCreate(BaseRequestModel):
    items: List[CartItem] # Usamos CartItem para la creación, luego se convierte a OrderItem
    shipping_address: Address
    shipping_zone: str = Field(..., description="Zona de envío: 'central', 'remote' o 'pickup'")
    # payment_method_id: str # ID del método de pago o de la pasarela si fuera necesario aquí

class Order(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    user_id: str
    items: List[OrderItem]
    total_amount: Money = Field(..., ge=0)
    status: OrderStatus = OrderStatus.PENDING
    shipping_address: Address
    shipping_zone: Optional[str] = Field(default="central", description="Zona de envío: 'central', 'remote' o 'pickup'")
    shipping_cost: Money = Field(default=Decimal("0.00"), description="Costo de envío según zona")
    payment_method: Optional[PaymentMethod] = None  # Método de pago seleccionado
    payment_id: Optional[str] = None # ID de la transacción de pago
    payment_preference_id: Optional[str] = None # ID de la preferencia de Mercado Pago
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    
    model_config = ConfigDict(
        populate_by_name=True,
    )

# Modelos para Pagos (Simplificado para la intención de la API)
class PaymentRequest(BaseModel):
    order_id: str = Field(..., description="ID del pedido a pagar")
    payment_method: str = Field(..., description="Método de pago (ej. 'MercadoPago', 'Tarjeta de Crédito')")
    amount: Money = Field(..., gt=0, description="Monto a pagar")
    # Podrías añadir más detalles específicos de la tarjeta aquí o dejar que la pasarela los maneje

# https://medium.com/@navneetskahlon/fastapi-and-pydantic-modern-data-validation-in-python-5fa0152f3588
class PaymentResponseModel(BaseModel): # Renombrado para evitar conflicto con PaymentResponse
    id: Optional[str] = Field(None, alias="_id")
    order_id: str
    user_id: str
    amount: Money
    currency: str = "ARS" # O la moneda predeterminada
    status: PaymentStatus = PaymentStatus.PENDING
    transaction_details: Optional[dict] = None # Detalles devueltos por la pasarela de pago
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    
    model_config = ConfigDict(
        populate_by_name=True,
    )

# Modelos para Gestión de Inventario / Alertas
class InventoryAlert(BaseModel):
    id: Optional[PyObjectId] = Field(None, alias="_id")
    product_id: str
    product_name: str
    current_stock: int
    threshold: int
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    
    model_config = ConfigDict(
        populate_by_name=True,
    )

# Modelos para Configuración de Pagos y Contacto
class PaymentSettings(BaseModel):
    """Configuración de métodos de pago y contacto (editable por admin)"""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    transfer_alias: str = Field(..., description="Alias bancario para transferencias")
    transfer_whatsapp: str = Field(..., description="Número de WhatsApp para comprobantes")
    instagram_url: Optional[str] = Field(None, description="URL de Instagram del negocio")
    facebook_url: Optional[str] = Field(None, description="URL de Facebook del negocio")
    email: Optional[str] = Field(None, description="Email de contacto del negocio")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_by: Optional[str] = None  # user_id del admin que actualizó
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True,
    )

class PaymentSettingsUpdate(BaseRequestModel):
    """Modelo para actualizar configuración de pagos y contacto"""
    transfer_alias: str = Field(..., min_length=3, max_length=100, description="Alias bancario")
    transfer_whatsapp: str = Field(..., pattern=r"^\+?[0-9]{10,15}$", description="Número de WhatsApp (10-15 dígitos)")
    instagram_url: Optional[str] = Field(None, max_length=200, description="URL de Instagram")
    facebook_url: Optional[str] = Field(None, max_length=200, description="URL de Facebook")
    email: Optional[str] = Field(None, description="Email de contacto")

# Modelos para Configuración de Envíos
class ShippingSettings(BaseModel):
    """Configuración de precios de envío por zona"""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    
    # Zona Central
    central_zone_enabled: bool = Field(default=True, description="Habilitar/deshabilitar envío a zona céntrica")
    central_zone_price: Money = Field(default=Decimal("0.00"), description="Precio de envío zona céntrica (GRATIS)")
    central_zone_description: str = Field(default="🎁 ENVÍO GRATIS - Zona Céntrica de Santa María", description="Descripción del envío a zona central")
    
    # Zona Remota
    remote_zone_enabled: bool = Field(default=True, description="Habilitar/deshabilitar envío a zonas alejadas")
    remote_zone_price: Money = Field(default=Decimal("1000.00"), description="Precio de envío zonas lejanas")
    remote_zone_description: str = Field(default="🚛 Envío a Zonas Alejadas", description="Descripción del envío a zona remota")
    
    # Retiro en Persona
    pickup_enabled: bool = Field(default=True, description="Habilitar/deshabilitar retiro en persona")
    pickup_address: str = Field(default="", description="Dirección para retiro en persona")
    pickup_price: Money = Field(default=Decimal("0.00"), description="Precio de retiro en persona (gratis)")
    pickup_description: str = Field(default="🏪 Retiro en Persona - GRATIS", description="Descripción de la opción de retiro")
    
    # Metadata
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_by: Optional[str] = None  # user_id del admin que actualizó
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True,
    )

# Modelos para Combos de Productos
class ComboItem(BaseRequestModel):
    """Item individual dentro de un combo"""
    product_id: str = Field(..., description="ID del producto que forma parte del combo")
    quantity: int = Field(..., gt=0, description="Cantidad de este producto en el combo")

class Combo(BaseModel):
    """Combo de productos (ej: Pack Previa, Pack Fernet)"""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str = Field(..., min_length=3, max_length=100, description="Nombre del combo")
    description: Optional[str] = Field(None, max_length=500, description="Descripción del combo")
    price: Money = Field(..., gt=0, description="Precio especial del combo")
    image_url: Optional[str] = Field(None, description="URL de la imagen del combo (CDN)")
    items: List[ComboItem] = Field(..., min_length=1, description="Productos que componen el combo")
    active: bool = Field(default=True, description="Si el combo está activo o no")
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True,
    )

class ComboCreate(BaseRequestModel):
    """Modelo para crear un combo"""
    name: str = Field(..., min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    price: Money = Field(..., gt=0)
    image_url: Optional[str] = None
    items: List[ComboItem] = Field(..., min_length=1)
    active: bool = True

class ComboUpdate(BaseRequestModel):
    """Modelo para actualizar un combo"""
    name: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    price: Optional[Money] = Field(None, gt=0)
    image_url: Optional[str] = None
    items: Optional[List[ComboItem]] = Field(None, min_length=1)
    active: Optional[bool] = None

# Modelos para respuesta enriquecida de combos
class ComboItemDetailed(BaseModel):
    """Item de combo con información completa del producto"""
    product_id: str = Field(..., description="ID del producto")
    quantity: int = Field(..., description="Cantidad en el combo")
    name: str = Field(..., description="Nombre del producto")
    price: Money = Field(..., description="Precio unitario del producto")
    image_url: Optional[str] = Field(None, description="URL de la imagen del producto")
    stock: int = Field(..., description="Stock disponible del producto")

class ComboDetailed(BaseModel):
    """Combo con información detallada de productos"""
    id: PyObjectId = Field(alias="_id")
    name: str
    description: Optional[str] = None
    price: Money
    image_url: Optional[str] = None
    items: List[ComboItemDetailed]
    active: bool
    created_at: datetime
    updated_at: datetime
    total_items_cost: Optional[Money] = Field(None, description="Suma del precio de todos los productos individuales")
    savings: Optional[Money] = Field(None, description="Ahorro al comprar el combo (total_items_cost - price)")
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True,
    )



# Modelos para Configuración de Precios Dinámicos (Weekend Pricing)
class DynamicPricingSettings(BaseModel):
    """Configuración para ajuste automático de precios (ej: de viernes a domingo)"""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    enabled: bool = Field(default=False, description="Activar o desactivar ajuste de precios automático")
    multiplier: Money = Field(default=Decimal("1.00"), description="Multiplicador de precio (ej: 0.9 para 10% de descuento, 1.1 para 10% de aumento)")
    start_day: int = Field(default=5, ge=1, le=7, description="Día de inicio (1=Lunes, 5=Viernes, 7=Domingo)")
    end_day: int = Field(default=7, ge=1, le=7, description="Día de fin")
    start_hour: int = Field(default=20, ge=0, le=23, description="Hora de inicio (0-23)")
    end_hour: int = Field(default=6, ge=0, le=23, description="Hora de fin (0-23)")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_by: Optional[str] = None  # user_id del admin que actualizó
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True,
    )

class DynamicPricingUpdate(BaseRequestModel):
    """Modelo para actualizar configuración de precios dinámicos"""
    enabled: bool
    multiplier: Money = Field(..., gt=0)
    start_day: int = Field(..., ge=1, le=7)
    end_day: int = Field(..., ge=1, le=7)
    start_hour: int = Field(..., ge=0, le=23)
    end_hour: int = Field(..., ge=0, le=23)

class BulkPriceUpdate(BaseRequestModel):
    """Modelo para actualizar precios masivamente"""
    percentage: Money = Field(..., description="Porcentaje de aumento (ej: 0.10 para 10%)")
    target: str = Field("all", description="Objetivo de la actualización: 'all' o ID de categoría")
    based_on: str = Field("price", description="Base para el aumento: 'price' (precio venta actual) o 'net_price' (precio costo)")


# Modelos para Configuración del Sistema (Modo Mantenimiento)
class SystemSettings(BaseModel):
    """Configuración global del sistema (ej: Modo Mantenimiento)"""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    maintenance_mode: bool = Field(default=False, description="Activar o desactivar modo mantenimiento")
    maintenance_message: str = Field(default="Estamos realizando mejoras. Volvemos pronto.", description="Mensaje para mostrar al usuario")
    allowed_ips: List[str] = Field(default=[], description="Lista de IPs permitidas durante mantenimiento (opcional)")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_by: Optional[str] = None
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
        arbitrary_types_allowed=True,
    )
