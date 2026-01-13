from bson import ObjectId
from pydantic import BaseModel, Field, EmailStr
from pydantic_core import core_schema
from typing import List, Optional, Any
from datetime import datetime
from pydantic.json_schema import JsonSchemaValue
import enum

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
    price: float = Field(..., gt=0, description="Precio de venta (mayor que cero)")
    category: ProductCategory = Field(..., description="Categoría de la bebida")
    stock: int = Field(..., ge=0, description="Cantidad disponible en inventario (mayor o igual a cero)")
    image_url: Optional[str] = Field(None, description="URL de la imagen principal del producto")
    abv: Optional[float] = Field(None, ge=0, le=100, description="Grado alcohólico por volumen (Alcohol by Volume), 0-100%")
    volume_ml: Optional[int] = Field(None, gt=0, description="Volumen del envase en mililitros")
    origin: Optional[str] = Field(None, max_length=50, description="País o región de origen")
    
    class Config:
        populate_by_name = True # Permite usar alias en el ID al crear o actualizar
        json_encoders = {ObjectId: str}
        arbitrary_types_allowed = True


# Modelos para Usuarios
class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Nombre de usuario único")
    email: EmailStr = Field(..., description="Correo electrónico válido")
    password: str = Field(..., min_length=8, description="Contraseña segura (mínimo 8 caracteres)")
    birth_date: datetime = Field(..., description="Fecha de nacimiento para verificación de edad")


class UserLogin(BaseModel):
    email_or_username: str = Field(..., description="Nombre de usuario o correo electrónico")
    password: str = Field(..., description="Contraseña")

class UserResponse(BaseModel):
    id: PyObjectId = Field(alias="_id")
    username: str
    email: EmailStr
    role: UserRole = UserRole.CUSTOMER # Por defecto, los nuevos usuarios son clientes
    age_verified: bool = False # Se actualizará después de la verificación
    birth_date: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: lambda v: str(v)}
        arbitrary_types_allowed = True


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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked: bool = Field(default=False, description="Si el token ha sido revocado")
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
        arbitrary_types_allowed = True

class AgeVerificationResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

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
class CartItem(BaseModel):
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
    price: float = Field(..., description="Precio unitario")
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
    price_at_purchase: float = Field(..., gt=0, description="Precio unitario del producto al momento de la compra")
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
        arbitrary_types_allowed = True

class Address(BaseModel):
    street: str
    city: str
    state: str
    zip_code: str
    country: str
    
class OrderCreate(BaseModel):
    items: List[CartItem] # Usamos CartItem para la creación, luego se convierte a OrderItem
    shipping_address: Address
    shipping_zone: str = Field(..., description="Zona de envío: 'central', 'remote' o 'pickup'")
    # payment_method_id: str # ID del método de pago o de la pasarela si fuera necesario aquí

class Order(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    user_id: str
    items: List[OrderItem]
    total_amount: float = Field(..., ge=0)
    status: OrderStatus = OrderStatus.PENDING
    shipping_address: Address
    shipping_zone: Optional[str] = Field(default="central", description="Zona de envío: 'central', 'remote' o 'pickup'")
    shipping_cost: float = Field(default=0.0, description="Costo de envío según zona")
    payment_method: Optional[PaymentMethod] = None  # Método de pago seleccionado
    payment_id: Optional[str] = None # ID de la transacción de pago
    payment_preference_id: Optional[str] = None # ID de la preferencia de Mercado Pago
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True

# Modelos para Pagos (Simplificado para la intención de la API)
class PaymentRequest(BaseModel):
    order_id: str = Field(..., description="ID del pedido a pagar")
    payment_method: str = Field(..., description="Método de pago (ej. 'MercadoPago', 'Tarjeta de Crédito')")
    amount: float = Field(..., gt=0, description="Monto a pagar")
    # Podrías añadir más detalles específicos de la tarjeta aquí o dejar que la pasarela los maneje

# https://medium.com/@navneetskahlon/fastapi-and-pydantic-modern-data-validation-in-python-5fa0152f3588
class PaymentResponseModel(BaseModel): # Renombrado para evitar conflicto con PaymentResponse
    id: Optional[str] = Field(None, alias="_id")
    order_id: str
    user_id: str
    amount: float
    currency: str = "ARS" # O la moneda predeterminada
    status: PaymentStatus = PaymentStatus.PENDING
    transaction_details: Optional[dict] = None # Detalles devueltos por la pasarela de pago
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True

# Modelos para Gestión de Inventario / Alertas
class InventoryAlert(BaseModel):
    id: Optional[PyObjectId] = Field(None, alias="_id")
    product_id: str
    product_name: str
    current_stock: int
    threshold: int
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True

# Modelos para Configuración de Pagos y Contacto
class PaymentSettings(BaseModel):
    """Configuración de métodos de pago y contacto (editable por admin)"""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    transfer_alias: str = Field(..., description="Alias bancario para transferencias")
    transfer_whatsapp: str = Field(..., description="Número de WhatsApp para comprobantes")
    instagram_url: Optional[str] = Field(None, description="URL de Instagram del negocio")
    email: Optional[str] = Field(None, description="Email de contacto del negocio")
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None  # user_id del admin que actualizó
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
        arbitrary_types_allowed = True

class PaymentSettingsUpdate(BaseModel):
    """Modelo para actualizar configuración de pagos y contacto"""
    transfer_alias: str = Field(..., min_length=3, max_length=100, description="Alias bancario")
    transfer_whatsapp: str = Field(..., pattern=r"^\+?[0-9]{10,15}$", description="Número de WhatsApp (10-15 dígitos)")
    instagram_url: Optional[str] = Field(None, max_length=200, description="URL de Instagram")
    email: Optional[str] = Field(None, description="Email de contacto")

# Modelos para Configuración de Envíos
class ShippingSettings(BaseModel):
    """Configuración de precios de envío por zona"""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    central_zone_price: float = Field(default=500.0, description="Precio de envío zona céntrica")
    central_zone_description: str = Field(default="Envío a zona céntrica", description="Descripción del envío a zona central")
    remote_zone_price: float = Field(default=1000.0, description="Precio de envío zonas lejanas")
    remote_zone_description: str = Field(default="Envío a zonas lejanas", description="Descripción del envío a zona remota")
    pickup_address: str = Field(default="", description="Dirección para retiro en persona")
    pickup_price: float = Field(default=0.0, description="Precio de retiro en persona (gratis)")
    pickup_description: str = Field(default="Retiro en persona", description="Descripción de la opción de retiro")
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None  # user_id del admin que actualizó
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
        arbitrary_types_allowed = True

# Modelos para Combos de Productos
class ComboItem(BaseModel):
    """Item individual dentro de un combo"""
    product_id: str = Field(..., description="ID del producto que forma parte del combo")
    quantity: int = Field(..., gt=0, description="Cantidad de este producto en el combo")

class Combo(BaseModel):
    """Combo de productos (ej: Pack Previa, Pack Fernet)"""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str = Field(..., min_length=3, max_length=100, description="Nombre del combo")
    description: Optional[str] = Field(None, max_length=500, description="Descripción del combo")
    price: float = Field(..., gt=0, description="Precio especial del combo")
    image_url: Optional[str] = Field(None, description="URL de la imagen del combo (CDN)")
    items: List[ComboItem] = Field(..., min_items=1, description="Productos que componen el combo")
    active: bool = Field(default=True, description="Si el combo está activo o no")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
        arbitrary_types_allowed = True

class ComboCreate(BaseModel):
    """Modelo para crear un combo"""
    name: str = Field(..., min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    price: float = Field(..., gt=0)
    image_url: Optional[str] = None
    items: List[ComboItem] = Field(..., min_items=1)
    active: bool = True

class ComboUpdate(BaseModel):
    """Modelo para actualizar un combo"""
    name: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    price: Optional[float] = Field(None, gt=0)
    image_url: Optional[str] = None
    items: Optional[List[ComboItem]] = Field(None, min_items=1)
    active: Optional[bool] = None

# Modelos para respuesta enriquecida de combos
class ComboItemDetailed(BaseModel):
    """Item de combo con información completa del producto"""
    product_id: str = Field(..., description="ID del producto")
    quantity: int = Field(..., description="Cantidad en el combo")
    name: str = Field(..., description="Nombre del producto")
    price: float = Field(..., description="Precio unitario del producto")
    image_url: Optional[str] = Field(None, description="URL de la imagen del producto")
    stock: int = Field(..., description="Stock disponible del producto")

class ComboDetailed(BaseModel):
    """Combo con información detallada de productos"""
    id: PyObjectId = Field(alias="_id")
    name: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None
    items: List[ComboItemDetailed]
    active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
        arbitrary_types_allowed = True


# Modelos para Configuración de Precios Dinámicos (Weekend Pricing)
class DynamicPricingSettings(BaseModel):
    """Configuración para ajuste automático de precios (ej: de viernes a domingo)"""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    enabled: bool = Field(default=False, description="Activar o desactivar ajuste de precios automático")
    multiplier: float = Field(default=1.0, description="Multiplicador de precio (ej: 0.9 para 10% de descuento, 1.1 para 10% de aumento)")
    start_day: int = Field(default=5, ge=1, le=7, description="Día de inicio (1=Lunes, 5=Viernes, 7=Domingo)")
    end_day: int = Field(default=7, ge=1, le=7, description="Día de fin")
    start_hour: int = Field(default=20, ge=0, le=23, description="Hora de inicio (0-23)")
    end_hour: int = Field(default=6, ge=0, le=23, description="Hora de fin (0-23)")
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None  # user_id del admin que actualizó
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
        arbitrary_types_allowed = True

class DynamicPricingUpdate(BaseModel):
    """Modelo para actualizar configuración de precios dinámicos"""
    enabled: bool
    multiplier: float = Field(..., gt=0)
    start_day: int = Field(..., ge=1, le=7)
    end_day: int = Field(..., ge=1, le=7)
    start_hour: int = Field(..., ge=0, le=23)
    end_hour: int = Field(..., ge=0, le=23)



