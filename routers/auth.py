from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import OAuth2PasswordRequestForm # Para el formulario de login OAuth2
from fastapi_limiter.depends import RateLimiter
from datetime import timedelta, datetime
from typing import Annotated
from pymongo.errors import DuplicateKeyError
from bson import ObjectId # Para manejar los IDs de MongoDB

from models import UserRegister, UserLogin, UserResponse, Token, TokenResponse, RefreshToken, UserRole, TokenData
from security import get_password_hash, verify_password, create_access_token, create_refresh_token, hash_token, verify_refresh_token, get_current_user_token_data
from database import get_database, get_collection
from config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Colección de usuarios en MongoDB
def get_users_collection(db=Depends(get_database)):
    return get_collection("users")

def get_refresh_tokens_collection(db=Depends(get_database)):
    return get_collection("refresh_tokens")

# --- Funciones Auxiliares para DB (simuladas por ahora) ---
# En un proyecto más grande, estas irían en una capa de servicios o repositorios.

async def get_user_by_username_or_email(collection, username_or_email: str):
    """Busca un usuario por username o email."""
    user = await collection.find_one({
        "$or": [
            {"username": username_or_email},
            {"email": username_or_email}
        ]
    })
    return user

async def create_user_in_db(collection, user_data: UserRegister) -> UserResponse:
    """Crea un nuevo usuario en la base de datos."""
    hashed_password = get_password_hash(user_data.password)
    
    # Preparamos el usuario para insertar
    user_dict = user_data.model_dump(exclude={"password", "birth_date"}) # Excluimos password, birth_date por ahora del dump directo
    user_dict["hashed_password"] = hashed_password
    user_dict["birth_date"] = user_data.birth_date # Guardamos la fecha de nacimiento para verificación
    user_dict["role"] = UserRole.CUSTOMER.value # Por defecto, todos son clientes
    user_dict["age_verified"] = False # Inicialmente no verificado

    try:
        result = await collection.insert_one(user_dict)
        if not result.inserted_id:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No se pudo crear el usuario.")
        
        # Recuperar el usuario insertado para devolver un UserResponse completo
        inserted_user = await collection.find_one({"_id": result.inserted_id})
        if inserted_user:
            return UserResponse(**inserted_user)
        else:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Usuario creado pero no se pudo recuperar.")

    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El nombre de usuario o correo electrónico ya está registrado."
        )
    except Exception as e:
        logger.error(f"Error al crear usuario en DB: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno del servidor al registrar usuario.")


# --- Endpoints de Autenticación ---
@router.post("/register", status_code=status.HTTP_201_CREATED, operation_id="auth_register_user")
async def register_user(
    user_data: UserRegister,
    users_collection = Depends(get_users_collection)
):
    """
    Registra un nuevo usuario en el sistema.
    Requiere username, email, contraseña y fecha de nacimiento.
    """
    # Verificar si el usuario ya existe
    existing_user = await get_user_by_username_or_email(users_collection, user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El nombre de usuario o correo electrónico ya está registrado."
        )
    existing_user = await get_user_by_username_or_email(users_collection, user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El nombre de usuario o correo electrónico ya está registrado."
        )

    # Crear el usuario en la base de datos
    new_user = await create_user_in_db(users_collection, user_data)
    
    logger.info(f"Usuario {new_user.username} registrado con éxito.")
    return new_user

# Se permitirán un máximo de 5 intentos de login por minuto desde la misma dirección IP. Si se supera, la API devolverá automáticamente un error 429 Too Many Requests.
@router.post("/token", response_model=TokenResponse, operation_id="auth_login_token", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    users_collection = Depends(get_users_collection),
    refresh_tokens_collection = Depends(get_refresh_tokens_collection)
):
    """
    Genera un token de acceso JWT y un refresh token para un usuario autenticado.
    Usa el estándar OAuth2 con username y password en un formulario.
    """
    user = await get_user_by_username_or_email(users_collection, form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nombre de usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Preparar datos para el token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Asegúrate de que los roles y age_verified se pasen correctamente
    user_roles = [UserRole(role) for role in user.get("role", [UserRole.CUSTOMER.value])] if isinstance(user.get("role"), list) else [UserRole(user.get("role", UserRole.CUSTOMER.value))]
    user_age_verified = user.get("age_verified", False)

    # Crear access token
    access_token = create_access_token(
        data={
            "sub": user["username"],
            "user_id": str(user["_id"]),
            "roles": [role.value for role in user_roles],
            "age_verified": user_age_verified
        },
        expires_delta=access_token_expires
    )
    
    # Crear refresh token
    refresh_token = create_refresh_token()
    refresh_token_expires = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    # Guardar refresh token hasheado en la base de datos
    refresh_token_data = {
        "token": hash_token(refresh_token),
        "user_id": str(user["_id"]),
        "expires_at": refresh_token_expires,
        "created_at": datetime.utcnow(),
        "revoked": False
    }
    await refresh_tokens_collection.insert_one(refresh_token_data)
    
    logger.info(f"Usuario {user['username']} ha iniciado sesión y recibido tokens.")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }

@router.post("/refresh", response_model=TokenResponse, operation_id="auth_refresh_token")
async def refresh_access_token(
    refresh_token: str,
    users_collection = Depends(get_users_collection),
    refresh_tokens_collection = Depends(get_refresh_tokens_collection)
):
    """
    Genera un nuevo access token usando un refresh token válido.
    El refresh token debe ser válido y no estar revocado.
    """
    # Buscar el refresh token en la base de datos
    refresh_token_docs = await refresh_tokens_collection.find({"revoked": False}).to_list(length=None)
    
    valid_token_doc = None
    for token_doc in refresh_token_docs:
        if verify_refresh_token(refresh_token, token_doc["token"]):
            valid_token_doc = token_doc
            break
    
    if not valid_token_doc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o revocado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verificar que no haya expirado
    if valid_token_doc["expires_at"] < datetime.utcnow():
        await refresh_tokens_collection.delete_one({"_id": valid_token_doc["_id"]})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Obtener el usuario
    user = await users_collection.find_one({"_id": ObjectId(valid_token_doc["user_id"])})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    # Preparar datos para el nuevo access token
    user_roles = [UserRole(role) for role in user.get("role", [UserRole.CUSTOMER.value])] if isinstance(user.get("role"), list) else [UserRole(user.get("role", UserRole.CUSTOMER.value))]
    user_age_verified = user.get("age_verified", False)
    
    # Crear nuevo access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    new_access_token = create_access_token(
        data={
            "sub": user["username"],
            "user_id": str(user["_id"]),
            "roles": [role.value for role in user_roles],
            "age_verified": user_age_verified
        },
        expires_delta=access_token_expires
    )
    
    # Crear nuevo refresh token
    new_refresh_token = create_refresh_token()
    new_refresh_token_expires = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    # Revocar el refresh token anterior
    await refresh_tokens_collection.update_one(
        {"_id": valid_token_doc["_id"]},
        {"$set": {"revoked": True}}
    )
    
    # Guardar el nuevo refresh token
    new_refresh_token_data = {
        "token": hash_token(new_refresh_token),
        "user_id": str(user["_id"]),
        "expires_at": new_refresh_token_expires,
        "created_at": datetime.utcnow(),
        "revoked": False
    }
    await refresh_tokens_collection.insert_one(new_refresh_token_data)
    
    logger.info(f"Usuario {user['username']} ha renovado su token de acceso.")
    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }

# --- Endpoint de prueba para verificar autenticación y obtener datos del usuario actual ---
@router.get("/me", response_model=UserResponse, operation_id="auth_get_current_user")
async def read_users_me(
    current_user_token_data: TokenData = Depends(get_current_user_token_data),
    users_collection = Depends(get_users_collection)
):
    """
    Obtiene los datos del usuario actualmente autenticado.
    Requiere un token JWT válido.
    """
    user = await users_collection.find_one({"_id": ObjectId(current_user_token_data.user_id)})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    # Convertir ObjectId a str para el UserResponse
    user["_id"] = str(user["_id"])
    return UserResponse(**user)

# --- Endpoint para verificar el rol del usuario (ejemplo) ---
@router.get("/admin-test", tags=["Admin"], status_code=status.HTTP_200_OK, operation_id="auth_admin_test")
async def admin_test(
    current_admin_user_data = Depends(get_current_user_token_data)
):
    """
    Endpoint de prueba para administradores.
    Solo accesible para usuarios con rol de administrador.
    """
    # Aquí podríamos hacer una verificación más explícita del rol si no usamos la dependencia de seguridad directamente
    if UserRole.ADMIN not in current_admin_user_data.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: Se requiere rol de administrador."
        )
    return {"message": f"Bienvenido administrador {current_admin_user_data.username}!"}