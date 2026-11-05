"""Router de Catálogo de Productos por Tienda (lectura general, escritura exclusiva para Admin)."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.product import Product
from app.models.store import Store
from app.models.user import User, UserRole
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate

router = APIRouter(prefix="/api/products", tags=["Productos"])


@router.get("", response_model=list[ProductRead])
def list_products(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    store_id: Annotated[int | None, Query(gt=0)] = None,
    include_unavailable: bool = False,
) -> list[Product]:
    """Lista el catálogo de productos filtrando opcionalmente por tienda."""
    stmt = select(Product).order_by(Product.store_id.asc(), Product.id.asc())

    if store_id is not None:
        stmt = stmt.where(Product.store_id == store_id)

    # Clientes solo ven productos disponibles; Admin y Operadores pueden ver agotados si lo piden
    if current_user.role == UserRole.CUSTOMER or not include_unavailable:
        stmt = stmt.where(Product.is_available.is_(True))

    return list(db.scalars(stmt).all())


@router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    payload: ProductCreate,
    _admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> Product:
    """Crea un producto dentro del catálogo de una tienda (exclusivo ADMIN)."""
    store = db.get(Store, payload.store_id)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La tienda con ID {payload.store_id} no existe.",
        )

    product = Product(
        store_id=store.id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        price=payload.price,
        is_available=payload.is_available,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    _admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> Product:
    """Actualiza precio, nombre, descripción o disponibilidad de un producto (exclusivo ADMIN)."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado.",
        )

    if payload.name is not None:
        product.name = payload.name.strip()
    if payload.description is not None:
        product.description = payload.description.strip()
    if payload.price is not None:
        product.price = payload.price
    if payload.is_available is not None:
        product.is_available = payload.is_available

    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    _admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Desactiva un producto del catálogo para preservar integridad referencial con pedidos históricos."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado.",
        )
    product.is_available = False
    db.commit()
