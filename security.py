from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from config import settings
from models import TokenData, UserRole, UserLogin # Importamos los modelos definidos
import logging

logger = logging.getLogger(__name__)

# Contexto para el hash de contraseñas. Usamos bcrypt, que es robusto.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configuración de OAuth2 para FastAPI, indica dónde obtener el token (nuestro endpoint de login)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token") # "auth/token" será nuestro endpoint de login

# --- Funciones para el Hash de Contraseñas ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica si una contraseña en texto plano coincide con una contraseña hasheada.
    """
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """
    Hashea una contraseña en texto plano.
    """
    return pwd_context.hash(password)

# --- Funciones para JSON Web Tokens (JWT) ---

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea un nuevo token de acceso JWT.
    data: Un diccionario con los datos a incluir en el payload del token (ej. username, user_id, roles).
    expires_delta: Opcional. Un timedelta para especificar la expiración. Si es None, usa el valor por defecto.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.utcnow()}) # Añade expiración y "issued at"
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def create_refresh_token() -> str:
    """
    Crea un refresh token aleatorio y seguro.
    Este token se almacenará hasheado en la base de datos.
    """
    import secrets
    return secrets.token_urlsafe(32)

def hash_token(token: str) -> str:
    """
    Hashea un token para almacenamiento seguro en la base de datos.
    """
    return pwd_context.hash(token)

def verify_refresh_token(plain_token: str, hashed_token: str) -> bool:
    """
    Verifica si un refresh token coincide con su versión hasheada.
    """
    return pwd_context.verify(plain_token, hashed_token)

def decode_access_token(token: str) -> TokenData:
    """
    Decodifica y valida un token JWT.
    Retorna un objeto TokenData si es válido.
    Lanza una HTTPException si el token es inválido o expira.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub") # 'sub' (subject) convencionalmente se usa para el identificador principal (username)
        user_id: str = payload.get("user_id")
        roles: List[str] = payload.get("roles", []) # Lista de roles del usuario
        age_verified: bool = payload.get("age_verified", False) # Estado de verificación de edad

        if username is None or user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales inválidas o token incompleto",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Convertir roles de str a UserRole enum
        user_roles = [UserRole(role) for role in roles if role in [r.value for r in UserRole]]

        token_data = TokenData(username=username, user_id=user_id, roles=user_roles, age_verified=age_verified)
        return token_data
    except JWTError:
        logger.warning(f"Error al decodificar JWT: {token}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

# --- Dependencias de FastAPI para Usuarios Autenticados y Roles ---

async def get_current_user_token_data(token: str = Depends(oauth2_scheme)) -> TokenData:
    """
    Dependencia de FastAPI que decodifica el token del usuario logueado.
    Retorna los datos del token si es válido.
    """
    return decode_access_token(token)

async def get_current_active_user_id(current_user_token_data: TokenData = Depends(get_current_user_token_data)) -> str:
    """
    Dependencia que obtiene el ID del usuario activo.
    """
    if not current_user_token_data.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no activo o ID de usuario no encontrado en el token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user_token_data.user_id


async def get_current_admin_user(current_user_token_data: TokenData = Depends(get_current_user_token_data)) -> TokenData:
    """
    Dependencia que verifica si el usuario actual es un administrador.
    """
    if UserRole.ADMIN not in current_user_token_data.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos de administrador para realizar esta acción",
        )
    return current_user_token_data

async def get_current_verified_user(current_user_token_data: TokenData = Depends(get_current_user_token_data)) -> TokenData:
    """
    Dependencia que verifica si el usuario actual ha confirmado su mayoría de edad.
    """
    if not current_user_token_data.age_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debes verificar tu mayoría de edad para acceder a este recurso.",
        )
    return current_user_token_data


def authenticate_user(user: UserLogin) -> dict:
    """
    Simula la autenticación de un usuario.
    En producción, deberías consultar la base de datos y verificar el hash de la contraseña.
    """
    # Simulación: usuario hardcodeado
    fake_user_db = {
        "admin@example.com": {
            "user_id": "123",
            "hashed_password": get_password_hash("123456"),
            "roles": ["admin"],
            "age_verified": True
        }
    }

    user_record = fake_user_db.get(user.email)
    if not user_record:
        return None

    if not verify_password(user.password, user_record["hashed_password"]):
        return None

    return {
        "username": user.email,
        "user_id": user_record["user_id"],
        "roles": user_record["roles"],
        "age_verified": user_record["age_verified"]
    }