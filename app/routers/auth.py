"""Router de Autenticación: Login con Rate Limiting, Registro de Clientes y Perfil actual."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import get_client_ip, rate_limiter
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserRead, UserRegisterCustomer

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """Autentica a un usuario con email/contraseña y devuelve un JWT firmado.

    Aplica Rate Limiting por IP para mitigar ataques de fuerza bruta.
    """
    client_ip = get_client_ip(request)
    rate_limiter.check(
        key=f"login:{client_ip}",
        max_requests=settings.RATE_LIMIT_LOGIN_PER_MINUTE,
        window_seconds=60,
    )

    stmt = select(User).where(User.email == payload.email.lower().strip())
    user = db.scalars(stmt).first()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas (correo o contraseña incorrectos).",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu cuenta se encuentra desactivada. Contacta al administrador.",
        )

    token = create_access_token(
        user_id=user.id,
        role=user.role,
        store_id=user.store_id,
    )
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def register_customer(
    payload: UserRegisterCustomer,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Permite el auto-registro únicamente con rol CUSTOMER (previene escalamiento de privilegios)."""
    email_clean = payload.email.lower().strip()
    existing = db.scalars(select(User).where(User.email == email_clean)).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un usuario registrado con ese correo electrónico.",
        )

    new_user = User(
        email=email_clean,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=UserRole.CUSTOMER,
        store_id=None,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.get("/me", response_model=UserRead)
def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Devuelve la información del usuario autenticado actualmente."""
    return current_user
