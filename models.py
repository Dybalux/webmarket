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
    product_id: str = Field(..., description="ID del producto en el carrito")
    quantity: int = Field(..., gt=0, description="Cantidad del producto (mayor que cero)")

class Cart(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    user_id: str = Field(..., description="ID del usuario propietario del carrito")
    items: List[CartItem] = [] # Lista de productos en el carrito
    
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
    # payment_method_id: str # ID del método de pago o de la pasarela si fuera necesario aquí

class Order(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    user_id: str
    items: List[OrderItem]
    total_amount: float = Field(..., ge=0)
    status: OrderStatus = OrderStatus.PENDING
    shipping_address: Address
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