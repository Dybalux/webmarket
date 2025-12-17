from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta 
from bson import ObjectId

from models import TokenData, UserResponse, Token, UserRole, AgeVerificationResponse
from security import get_current_user_token_data, create_access_token # Para saber quién es el usuario
from database import get_database, get_collection
from config import settings
import logging

# Configuración de logging
logger = logging.getLogger(__name__)
router = APIRouter()

# Definir la edad mínima legal (ej. 18 años)
MINIMUM_AGE = 18

# Colección de usuarios en MongoDB
def get_users_collection(db=Depends(get_database)):
    return get_collection("users")

@router.post("/verify-age", response_model=AgeVerificationResponse, status_code=status.HTTP_200_OK)
async def verify_age(
    current_user_token_data: TokenData = Depends(get_current_user_token_data),
    users_collection=Depends(get_users_collection)
):
    """
    Endpoint para verificar o re-verificar la mayoría de edad del usuario autenticado.
    Actualiza el estado 'age_verified' del usuario si cumple la edad mínima.
    Retorna un nuevo token JWT con age_verified actualizado.
    """

    user_id = current_user_token_data.user_id

    #Obtener el usuario de la DB para acceder a su fecha de nacimiento
    user_db = await users_collection.find_one({"_id": ObjectId(user_id)})

    if not user_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en la base de datos."
        )
    
    #Calcular la edad del usuario

    birth_date = user_db.get("birth_date")
    if not birth_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fecha de nacimiento no registrada para este usuario. Por favor, actualiza tu perfil."
        )
    
    today = datetime.utcnow()
    age = relativedelta(today, birth_date).years
    if age < MINIMUM_AGE:
        # Si el usuario es menor de edad, forzamos age_verified a False y respondemos con error
        if user_db.get("age_verified"):
            # Si por alguna razón estaba verificado, lo desverificamos
            await users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"age_verified": False, "updated_at": datetime.utcnow()}}
            )
            logger.warning(f"Usuario {user_db['username']} (ID: {user_id}) era menor de edad pero estaba verificado. Estado corregido a no verificado.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Debes tener al menos {MINIMUM_AGE} años para acceder a productos alcohólicos. Tu edad es {age}."
        )
    else:
        # Si el usuario es mayor de edad, aseguramos que age_verified sea True
        if not user_db.get("age_verified"):
            await users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"age_verified": True, "updated_at": datetime.utcnow()}}
            )
            logger.info(f"Usuario {user_db['username']} (ID: {user_id}) ha verificado su mayoría de edad. Ahora tiene {age} años.")
        
        # Recuperar el usuario actualizado para la respuesta
        updated_user_db = await users_collection.find_one({"_id": ObjectId(user_id)})
        
        # Generar un nuevo token JWT con age_verified actualizado
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        
        # Obtener roles del usuario
        user_roles = [UserRole(role) for role in updated_user_db.get("role", [UserRole.CUSTOMER.value])] if isinstance(updated_user_db.get("role"), list) else [UserRole(updated_user_db.get("role", UserRole.CUSTOMER.value))]
        
        new_token = create_access_token(
            data={
                "sub": updated_user_db["username"],
                "user_id": str(updated_user_db["_id"]),
                "roles": [role.value for role in user_roles],
                "age_verified": True  # Ahora el token refleja el estado actualizado
            },
            expires_delta=access_token_expires
        )
        
        # Convertir ObjectId a str para el UserResponse
        updated_user_db["_id"] = str(updated_user_db["_id"])
        
        return {
            "access_token": new_token,
            "token_type": "bearer",
            "user": UserResponse(**updated_user_db)
        }
    
#Puedes añadir un endpoint para obtener la edad mínima si el frontend lo necesita

@router.get("/minimun-age", response_model=dict)
async def get_minimum_age():
    """
    Retorna la edad mínima requerida para la compra de bebidas alcohólicas.
    """
    return {"minimum_age": MINIMUM_AGE}

    
