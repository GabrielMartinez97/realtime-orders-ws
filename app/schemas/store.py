"""Esquemas Pydantic v2 para Tiendas (Stores)."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class StoreBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    address: str = Field(..., min_length=5, max_length=255)


class StoreCreate(StoreBase):
    """Datos requeridos para crear una nueva tienda (solo Admin)."""


class StoreUpdate(BaseModel):
    """Campos opcionales para actualizar una tienda."""

    name: Optional[str] = Field(None, min_length=2, max_length=100)
    address: Optional[str] = Field(None, min_length=5, max_length=255)
    is_active: Optional[bool] = None


class StoreRead(StoreBase):
    """Representación pública de una tienda."""

    id: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
