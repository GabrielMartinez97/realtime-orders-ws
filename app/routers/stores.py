"""Router de Tiendas (Stores): listado general y CRUD exclusivo para Administradores."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.store import Store
from app.models.user import User, UserRole
from app.schemas.store import StoreCreate, StoreRead, StoreUpdate

router = APIRouter(prefix="/api/stores", tags=["Tiendas"])


@router.get("", response_model=list[StoreRead])
def list_stores(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[Store]:
    """Lista las tiendas. Los clientes y operadores ven las activas; el Admin ve todas."""
    stmt = select(Store).order_by(Store.id.asc())
    if current_user.role != UserRole.ADMIN:
        stmt = stmt.where(Store.is_active.is_(True))
    return list(db.scalars(stmt).all())


@router.post(
    "",
    response_model=StoreRead,
    status_code=status.HTTP_201_CREATED,
)
def create_store(
    payload: StoreCreate,
    _admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> Store:
    """Crea una nueva tienda (exclusivo para rol ADMIN)."""
    name_clean = payload.name.strip()
    existing = db.scalars(select(Store).where(Store.name == name_clean)).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una tienda con el nombre '{name_clean}'.",
        )

    store = Store(name=name_clean, address=payload.address.strip(), is_active=True)
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


@router.patch("/{store_id}", response_model=StoreRead)
def update_store(
    store_id: int,
    payload: StoreUpdate,
    _admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> Store:
    """Actualiza los datos o estado activo de una tienda (exclusivo para rol ADMIN)."""
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tienda no encontrada.",
        )

    if payload.name is not None:
        store.name = payload.name.strip()
    if payload.address is not None:
        store.address = payload.address.strip()
    if payload.is_active is not None:
        store.is_active = payload.is_active

    db.commit()
    db.refresh(store)
    return store
