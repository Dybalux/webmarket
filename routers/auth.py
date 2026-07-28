from fastapi import APIRouter, Depends, HTTPException, Request, status, Response
from fastapi.security import OAuth2PasswordRequestForm # Para el formulario de login OAuth2
from fastapi_limiter.depends import RateLimiter
from datetime import datetime, timezone, timedelta
from typing import Annotated
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from dateutil.relativedelta import relativedelta

from models import UserRegister, UserLogin, UserResponse, Token, TokenResponse, RefreshToken, UserRole, TokenData, ForgotPasswordRequest, PasswordResetConfirm
from security import (
    get_password_hash, verify_password, create_access_token, create_refresh_token,
    hash_token, verify_refresh_token, get_current_user_token_data,
    get_redis, check_lockout, record_failure, clear_failures,
    create_reset_token, hash_reset_token,
)
from email_service import send_password_reset_email
from database import get_database, get_collection
from config import settings
import audit_logger
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
    
    # Calcular la edad del usuario automáticamente
    MINIMUM_AGE = 18
    today = datetime.now(tz=timezone.utc)
    birth_date = user_data.birth_date
    
    # Comparar en naive UTC para evitar TypeError offset-naive vs offset-aware
    if birth_date.tzinfo is not None:
        birth_date = birth_date.replace(tzinfo=None)
    today = today.replace(tzinfo=None)
    
    age = relativedelta(today, birth_date).years
    
    # Verificar automáticamente la edad
    age_verified = age >= MINIMUM_AGE
    
    # Preparamos el usuario para insertar
    user_dict = user_data.model_dump(exclude={"password", "birth_date"}) # Excluimos password, birth_date por ahora del dump directo
    user_dict["hashed_password"] = hashed_password
    user_dict["birth_date"] = user_data.birth_date # Guardamos la fecha de nacimiento para verificación
    user_dict["role"] = UserRole.CUSTOMER.value # Por defecto, todos son clientes
    user_dict["age_verified"] = age_verified # Se verifica automáticamente si tiene 18+ años
    user_dict["created_at"] = datetime.now(tz=timezone.utc)

    try:
        result = await collection.insert_one(user_dict)
        if not result.inserted_id:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No se pudo crear el usuario.")
        
        # Recuperar el usuario insertado para devolver un UserResponse completo
        inserted_user = await collection.find_one({"_id": result.inserted_id})
        if inserted_user:
            logger.info(f"Usuario {inserted_user['username']} registrado con age_verified={age_verified} (edad: {age} años)")
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
    request: Request,
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
    await audit_logger.log_audit(
        audit_logger.AuditEvent.USER_REGISTERED, request,
        {"username": new_user.username},
    )
    return new_user

# Se permitirán un máximo de 5 intentos de login por minuto desde la misma dirección IP. Si se supera, la API devolverá automáticamente un error 429 Too Many Requests.
@router.post("/token", response_model=TokenResponse, operation_id="auth_login_token", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    users_collection = Depends(get_users_collection),
    refresh_tokens_collection = Depends(get_refresh_tokens_collection),
    redis_client = Depends(get_redis),
):
    """
    Genera un token de acceso JWT y un refresh token para un usuario autenticado.
    Usa el estándar OAuth2 con username y password en un formulario.
    """
    # F-017: per-account lockout (runs after IP rate limiter, before verify_password)
    remaining = await check_lockout(redis_client, form_data.username)
    if remaining > 0:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account locked. Try again in {remaining} seconds.",
        )

    user = await get_user_by_username_or_email(users_collection, form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        # F-017: record failure after bad credentials
        await record_failure(redis_client, form_data.username)
        await audit_logger.log_audit(
            audit_logger.AuditEvent.USER_LOGIN_FAILED, request,
            {"username": form_data.username},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nombre de usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # F-017: success — clear any accumulated failures
    await clear_failures(redis_client, user["username"])

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
    refresh_token_expires = datetime.now(tz=timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    # Guardar refresh token hasheado en la base de datos
    refresh_token_data = {
        "token": hash_token(refresh_token),
        "user_id": str(user["_id"]),
        "expires_at": refresh_token_expires,
        "created_at": datetime.now(tz=timezone.utc),
        "revoked": False
    }
    await refresh_tokens_collection.insert_one(refresh_token_data)
    
    logger.info(f"Usuario {user['username']} ha iniciado sesión y recibido tokens.")
    await audit_logger.log_audit(
        audit_logger.AuditEvent.USER_LOGIN_SUCCESS, request,
        {"username": user["username"]},
    )
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
    # Buscar el refresh token en la base de datos.
    # NOTA: los refresh tokens se almacenan hasheados con bcrypt, por lo que
    # no se pueden buscar directamente por su valor. Para evitar cargar TODOS
    # los tokens en memoria, filtramos por expirados y limitamos el cursor.
    now = datetime.now(tz=timezone.utc)
    cursor = refresh_tokens_collection.find({
        "revoked": False,
        "expires_at": {"$gt": now}
    }).limit(50)

    valid_token_doc = None
    async for token_doc in cursor:
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
    if valid_token_doc["expires_at"] < datetime.now(tz=timezone.utc):
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
    new_refresh_token_expires = datetime.now(tz=timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
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
        "created_at": datetime.now(tz=timezone.utc),
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


# --- Password reset endpoints (F-015) ---

@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED, operation_id="auth_forgot_password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    users_collection = Depends(get_users_collection),
):
    """
    Initiates a password reset. Always returns 202 with an identical body
    regardless of whether the email exists (enumeration-resistant).
    """
    user = await users_collection.find_one({"email": body.email})

    if user:
        token = create_reset_token()
        token_hash = hash_reset_token(token)

        reset_tokens = get_collection("password_reset_tokens")
        await reset_tokens.insert_one({
            "token_hash": token_hash,
            "user_id": str(user["_id"]),
            "expires_at": datetime.now(tz=timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
            "used": False,
        })

        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        await send_password_reset_email(body.email, reset_url)

    # Identical response whether user exists or not — no enumeration
    await audit_logger.log_audit(
        audit_logger.AuditEvent.PASSWORD_RESET_REQUESTED, request,
        {"email": body.email},
    )
    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password", status_code=status.HTTP_200_OK, operation_id="auth_reset_password")
async def reset_password(
    body: PasswordResetConfirm,
    request: Request,
    users_collection = Depends(get_users_collection),
):
    """
    Consumes a single-use reset token and updates the user's password.
    Token is consumed atomically via find_one_and_update.
    """
    token_hash = hash_reset_token(body.token)
    reset_tokens = get_collection("password_reset_tokens")

    # Atomic single-use consumption
    doc = await reset_tokens.find_one_and_update(
        {
            "token_hash": token_hash,
            "used": False,
            "expires_at": {"$gt": datetime.now(tz=timezone.utc)},
        },
        {"$set": {"used": True}},
    )

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, or already-used reset token.",
        )

    # Update password
    hashed = get_password_hash(body.new_password)
    await users_collection.update_one(
        {"_id": ObjectId(doc["user_id"])},
        {"$set": {"hashed_password": hashed}},
    )

    await audit_logger.log_audit(
        audit_logger.AuditEvent.PASSWORD_RESET_COMPLETED, request,
        {"user_id": doc["user_id"]},
    )
    return {"message": "Password updated successfully."}