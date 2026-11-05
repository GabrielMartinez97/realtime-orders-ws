"""Esquemas Pydantic v2 para Usuarios."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserRegisterCustomer(BaseModel):
    """Esquema seguro para auto-registro de Clientes (no permite elegir rol ni tienda)."""

    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)


class UserCreateByAdmin(BaseModel):
    """Esquema exclusivo para Administradores: permite crear Operadores, Admins o Clientes."""

    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = UserRole.CUSTOMER
    store_id: Optional[int] = None


class UserRead(BaseModel):
    """Representación pública de un usuario (sin exponer jamás password_hash)."""

    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    store_id: Optional[int] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
