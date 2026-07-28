from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from typing import Optional
from decimal import Decimal
from bson import ObjectId

from motor.motor_asyncio import AsyncIOMotorDatabase

from models import Product, ProductCategory, TokenData, AdminProduct, ProductUpdate
from database import get_database
from security import get_current_admin_user
from services import products as products_service

router = APIRouter()


# ---------------------------------------------------------------------------
# POST / — create product
# ---------------------------------------------------------------------------


@router.post("/", response_model=AdminProduct, status_code=status.HTTP_201_CREATED)
async def create_product(
    product: AdminProduct,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: TokenData = Depends(get_current_admin_user),
):
    """
    Crea un nuevo producto (bebida) en el catálogo.
    Requiere permisos de administrador.
    """
    return await products_service.create_product(db, product, current_user.user_id)


# ---------------------------------------------------------------------------
# GET / — list products (public)
# ---------------------------------------------------------------------------


@router.get("/")
async def read_products(
    db: AsyncIOMotorDatabase = Depends(get_database),
    category: Optional[ProductCategory] = Query(None, description="Filtrar por categoría de producto"),
    min_price: Optional[Decimal] = Query(None, ge=0, description="Precio mínimo del producto"),
    max_price: Optional[Decimal] = Query(None, ge=0, description="Precio máximo del producto"),
    search: Optional[str] = Query(None, min_length=2, description="Buscar por nombre o descripción del producto"),
    include_out_of_stock: bool = Query(False, description="Incluir productos sin stock (para administradores)"),
    page: int = Query(1, ge=1, description="Número de página (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Tamaño de página"),
):
    """
    Obtiene una lista paginada de productos con opciones de filtrado y búsqueda.
    Por defecto, solo muestra productos con stock disponible (stock > 0).
    Usar include_out_of_stock=true para ver todos los productos (útil para administradores).
    Accesible para cualquier usuario (no requiere autenticación).
    """
    skip = (page - 1) * page_size
    return await products_service.list_products(
        db,
        skip=skip,
        limit=page_size,
        category=category,
        min_price=min_price,
        max_price=max_price,
        search=search,
        include_out_of_stock=include_out_of_stock,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /{product_id} — get single product (public)
# ---------------------------------------------------------------------------


@router.get("/{product_id}", response_model=Product)
async def read_product(
    product_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Obtiene los detalles de un producto específico por su ID.
    Accesible para cualquier usuario.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    return await products_service.get_product(db, product_id)


# ---------------------------------------------------------------------------
# PUT /{product_id} — update product (admin)
# ---------------------------------------------------------------------------


@router.put("/{product_id}", response_model=AdminProduct)
async def update_product(
    product_id: str,
    product_update: ProductUpdate,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """
    Actualiza la información de un producto existente.
    Soporta cálculo automático de precio si se envía 'profit_percentage'.
    Requiere permisos de administrador.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    return await products_service.update_product(
        db, product_id, product_update, current_admin_user.user_id
    )


# ---------------------------------------------------------------------------
# DELETE /{product_id} — delete product (admin)
# ---------------------------------------------------------------------------


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """
    Elimina un producto del catálogo por su ID.
    Requiere permisos de administrador.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    await products_service.delete_product(db, product_id, current_admin_user.user_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# PATCH /{product_id}/toggle-active — toggle product active state (admin)
# ---------------------------------------------------------------------------


@router.patch("/{product_id}/toggle-active", response_model=AdminProduct)
async def toggle_product_active(
    product_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """
    Activa o desactiva un producto (soft delete).
    Requiere permisos de administrador.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de producto inválido.")

    return await products_service.toggle_product_active(
        db, product_id, current_admin_user.user_id
    )
