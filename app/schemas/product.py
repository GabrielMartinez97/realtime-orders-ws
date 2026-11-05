"""Esquemas Pydantic v2 para el catálogo de Productos."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    """Datos requeridos para crear un producto en el catálogo de una tienda (solo Admin)."""

    store_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=2, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    price: Decimal = Field(..., gt=Decimal("0.00"), max_digits=10, decimal_places=2)
    is_available: bool = True


class ProductUpdate(BaseModel):
    """Campos opcionales para actualizar un producto existente (solo Admin)."""

    name: Optional[str] = Field(None, min_length=2, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    price: Optional[Decimal] = Field(None, gt=Decimal("0.00"), max_digits=10, decimal_places=2)
    is_available: Optional[bool] = None


class ProductRead(BaseModel):
    """Representación de un producto."""

    id: int
    store_id: int
    name: str
    description: Optional[str] = None
    price: Decimal
    image_path: Optional[str] = None
    is_available: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
