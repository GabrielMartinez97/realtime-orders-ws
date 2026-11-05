"""Esquemas Pydantic v2 para Pedidos, Ítems e Historial de Estados."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus


class OrderItemCreate(BaseModel):
    """Ítem solicitado al crear un pedido.

    Nota de seguridad: NO aceptamos precio desde el cliente. El servidor
    consulta el precio real en la base de datos para evitar manipulación.
    """

    product_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0, le=100)


class OrderCreate(BaseModel):
    """Payload enviado por un Cliente para crear un nuevo pedido."""

    store_id: int = Field(..., gt=0)
    notes: Optional[str] = Field(None, max_length=500)
    items: list[OrderItemCreate] = Field(..., min_length=1, max_length=50)


class OrderStatusUpdate(BaseModel):
    """Payload para cambiar el estado de un pedido con registro de auditoría."""

    status: OrderStatus
    comment: Optional[str] = Field(None, max_length=255)


class OrderItemRead(BaseModel):
    """Representación de una línea de pedido con precios congelados (snapshot)."""

    id: int
    product_id: int
    product_name_snapshot: str
    unit_price_snapshot: Decimal
    quantity: int
    subtotal: Decimal

    model_config = ConfigDict(from_attributes=True)


class OrderStatusHistoryRead(BaseModel):
    """Entrada del historial de auditoría de estados."""

    id: int
    order_id: int
    from_status: Optional[OrderStatus] = None
    to_status: OrderStatus
    changed_by_user_id: int
    comment: Optional[str] = None
    changed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderRead(BaseModel):
    """Representación completa de un pedido incluyendo ítems e historial."""

    id: int
    customer_id: int
    store_id: int
    status: OrderStatus
    total_amount: Decimal
    notes: Optional[str] = None
    payment_receipt_path: Optional[str] = None
    created_at: datetime
    ready_at: Optional[datetime] = None
    updated_at: datetime
    items: list[OrderItemRead] = []
    status_history: list[OrderStatusHistoryRead] = []

    model_config = ConfigDict(from_attributes=True)
