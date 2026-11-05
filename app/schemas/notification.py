"""Esquemas Pydantic v2 para Notificaciones persistidas y en tiempo real."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    """Representación pública de una notificación."""

    id: int
    user_id: int
    order_id: Optional[int] = None
    event_type: str
    title: str
    message: str
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationsSummaryRead(BaseModel):
    """Resumen de notificaciones del usuario con contador de no leídas."""

    unread_count: int
    items: list[NotificationRead]
