"""Router de Usuarios: gestión administrativa de cuentas y asignación de Operadores a Tiendas."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_password, require_roles
from app.models.store import Store
from app.models.user import User, UserRole
from app.schemas.user import UserCreateByAdmin, UserRead

router = APIRouter(prefix="/api/users", tags=["Usuarios (Admin)"])


@router.get("", response_model=list[UserRead])
def list_users(
    _admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> list[User]:
    """Lista todos los usuarios registrados en el sistema (exclusivo ADMIN)."""
    stmt = select(User).order_by(User.id.asc())
    return list(db.scalars(stmt).all())


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def create_user_by_admin(
    payload: UserCreateByAdmin,
    _admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Crea un usuario con cualquier rol. Valida que todo OPERATOR tenga una tienda válida asignada."""
    email_clean = payload.email.lower().strip()
    existing = db.scalars(select(User).where(User.email == email_clean)).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un usuario con ese correo electrónico.",
        )

    if payload.role == UserRole.OPERATOR:
        if payload.store_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un usuario con rol OPERATOR debe tener un store_id asignado obligatoriamente.",
            )
        store = db.get(Store, payload.store_id)
        if store is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"La tienda con ID {payload.store_id} no existe.",
            )
        assigned_store_id = store.id
    else:
        assigned_store_id = None

    new_user = User(
        email=email_clean,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        store_id=assigned_store_id,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user
