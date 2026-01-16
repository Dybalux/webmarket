from fastapi import APIRouter, Depends, HTTPException, status , Query, Response
from typing import List, Optional
from bson import ObjectId

from models import Product, ProductCategory, UserRole, TokenData, PaginationMeta, DynamicPricingSettings, AdminProduct, ProductUpdate
from database import get_database, get_collection
from security import get_current_admin_user # Importamos la dependencia para admins
from pricing_helpers import get_adjusted_price
from routers.pricing_settings import get_pricing_settings_collection
from datetime import datetime
import logging
import math

logger = logging.getLogger(__name__)

router = APIRouter()

#Coleccion de productos
def get_products_collection():
    return get_collection("products")

#Endpoint para la gestión de productos
@router.post("/", response_model=AdminProduct, status_code=status.HTTP_201_CREATED)
async def create_product(
    product: AdminProduct,
    products_collection = Depends(get_products_collection),
    # Solo admins pueden crear productos
    current_user: TokenData = Depends(get_current_admin_user)  
):
    """ 
    Crea un nuevo producto (bebida) en el catálogo.
    Requiere permisos de administrador.
    """
    # Validar que el nombre del producto no esté duplicado
    existing_product = await products_collection.find_one({"name": product.name})
    if existing_product:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El nombre del producto ya existe."
        )
    product_dict = product.model_dump(exclude_unset=True, exclude={"id"}, by_alias=True)
    result = await products_collection.insert_one(product_dict)
    
    if not result.inserted_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No se pudo crear el producto.")
    
    # Obtener el producto recién creado para devolver el ID
    created_product = await products_collection.find_one({"_id": result.inserted_id})
    if created_product:
        return AdminProduct.model_validate(created_product)
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Producto creado pero no se pudo recuperar.")

    
@router.get("/")
async def read_products(
    products_collection = Depends(get_products_collection),
    category: Optional[ProductCategory] = Query(None, description="Filtrar por categoría de producto"),
    min_price: Optional[float] = Query(None, ge=0, description="Precio mínimo del producto"),
    max_price: Optional[float] = Query(None, ge=0, description="Precio máximo del producto"),
    search: Optional[str] = Query(None, min_length=2, description="Buscar por nombre o descripción del producto"),
    include_out_of_stock: bool = Query(False, description="Incluir productos sin stock (para administradores)"),
    page: int = Query(1, ge=1, description="Número de página (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Tamaño de página"),
    pricing_settings_collection = Depends(get_pricing_settings_collection)
):
    """
    Obtiene una lista paginada de productos con opciones de filtrado y búsqueda.
    Por defecto, solo muestra productos con stock disponible (stock > 0).
    Usar include_out_of_stock=true para ver todos los productos (útil para administradores).
    Accesible para cualquier usuario (no requiere autenticación).
    """
    query = {}
    
    # SIEMPRE filtrar solo productos activos en el endpoint público
    query["active"] = True
    
    # Filtrar solo productos con stock disponible (a menos que se solicite lo contrario)
    if not include_out_of_stock:
        query["stock"] = {"$gt": 0}
    
    if category:
        query["category"] = category.value
    if min_price is not None:
        query["price"] = {"$gte": min_price}
    if max_price is not None:
        if "price" in query:
            query["price"]["$lte"] = max_price
        else:
            query["price"] = {"$lte": max_price}
    if search:
        # Búsqueda insensible a mayúsculas/minúsculas en nombre y descripción
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}}
        ]

    # Contar total de items
    total = await products_collection.count_documents(query)
    
    # Calcular paginación
    skip = (page - 1) * page_size
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    
    # Obtener configuración de precios dinámicos
    pricing_doc = await pricing_settings_collection.find_one({})
    pricing_settings = DynamicPricingSettings(**pricing_doc) if pricing_doc else DynamicPricingSettings()

    # Obtener productos paginados
    products_cursor = products_collection.find(query).skip(skip).limit(page_size)
    products_list = []
    async for product_doc in products_cursor:
        product = Product(**product_doc)
        # Aplicar precio dinámico
        product.price = get_adjusted_price(product.price, pricing_settings)
        products_list.append(product)
    
    # Construir metadatos de paginación
    meta = PaginationMeta(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1
    )
    
    return {
        "items": products_list,
        "meta": meta
    }

@router.get("/{product_id}", response_model=Product)
async def read_product(
    product_id: str,
    products_collection = Depends(get_products_collection),
    pricing_settings_collection = Depends(get_pricing_settings_collection)
):
    """
    Obtiene los detalles de un producto específico por su ID.
    Accesible para cualquier usuario.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    product_db = await products_collection.find_one({"_id": ObjectId(product_id), "active": True})
    if product_db:
        product = Product(**product_db)
        # Obtener configuración de precios dinámicos
        pricing_doc = await pricing_settings_collection.find_one({})
        pricing_settings = DynamicPricingSettings(**pricing_doc) if pricing_doc else DynamicPricingSettings()
        # Aplicar precio dinámico
        product.price = get_adjusted_price(product.price, pricing_settings)
        return product
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")


@router.put("/{product_id}", response_model=AdminProduct)
async def update_product(
    product_id: str,
    product_update: ProductUpdate, # Usamos ProductUpdate para permitir campos opcionales y porcentaje de ganancia
    products_collection = Depends(get_products_collection),
    # Solo administradores pueden actualizar productos
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    Actualiza la información de un producto existente.
    Soporta cálculo automático de precio si se envía 'profit_percentage'.
    Requiere permisos de administrador.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    # 1. Obtener producto actual para cálculos o validación
    current_product = await products_collection.find_one({"_id": ObjectId(product_id)})
    if not current_product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")

    # 2. Convertir el modelo Pydantic a un diccionario, excluyendo campos no seteados
    update_data = product_update.model_dump(exclude_unset=True)
    
    # 3. Lógica de cálculo de precio por porcentaje de ganancia
    if "profit_percentage" in update_data:
        profit_pct = update_data.pop("profit_percentage")
        
        # Necesitamos el precio neto para calcular
        # Lo buscamos en los datos de actualización, o usamos el existente en DB
        net_price = update_data.get("net_price")
        if net_price is None:
            net_price = current_product.get("net_price")
            
        if net_price is not None:
            # Calcular nuevo precio de venta: neto * (1 + ganancia/100)
            calculated_price = round(net_price * (1 + profit_pct / 100), 2)
            update_data["price"] = calculated_price
            logger.info(f"Precio calculado automáticamente: {calculated_price} (Neto: {net_price}, Ganancia: {profit_pct}%)")
        else:
            # Si no hay precio neto ni en el update ni en la DB, no podemos calcular
            logger.warning(f"No se pudo calcular el precio para {product_id} porque falta 'net_price'")

    # 4. No permitir cambiar el ID
    for key in ["_id", "id"]:
        if key in update_data:
            del update_data[key]

    if not update_data:
        # Si no hay nada que actualizar tras procesar
        return AdminProduct(**current_product)

    # 5. Ejecutar actualización
    result = await products_collection.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": update_data}
    )

    updated_product = await products_collection.find_one({"_id": ObjectId(product_id)})
    return AdminProduct(**updated_product)



@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: str,
    products_collection = Depends(get_products_collection),
    # Solo administradores pueden eliminar productos
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    Elimina un producto del catálogo por su ID.
    Requiere permisos de administrador.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    result = await products_collection.delete_one({"_id": ObjectId(product_id)})

    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado para eliminar.")
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{product_id}/toggle-active", response_model=AdminProduct)
async def toggle_product_active(
    product_id: str,
    products_collection = Depends(get_products_collection),
    current_admin_user: TokenData = Depends(get_current_admin_user)
):
    """
    Activa o desactiva un producto (soft delete).
    Requiere permisos de administrador.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    product = await products_collection.find_one({"_id": ObjectId(product_id)})
    
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")
    
    # Cambiar el estado actual
    new_active_state = not product.get("active", True)
    
    await products_collection.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"active": new_active_state}}
    )
    
    updated_product = await products_collection.find_one({"_id": ObjectId(product_id)})
    return AdminProduct(**updated_product)
