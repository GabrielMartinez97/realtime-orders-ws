"""Esquemas Pydantic v2 para eventos y mensajes WebSocket tipados."""

import enum
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WSServerEventType(str, enum.Enum):
    """Tipos de eventos emitidos desde el Servidor hacia el Cliente por WebSocket."""

    CONNECTION_ESTABLISHED = "connection_established"
    PONG = "pong"
    SUBSCRIBED = "subscribed"
    ORDER_CREATED = "pedido_creado"
    STATUS_UPDATED = "estado_actualizado"
    NOTIFICATION = "notificacion"
    DASHBOARD_UPDATE = "dashboard_update"
    ERROR = "error"


class WSClientActionType(str, enum.Enum):
    """Acciones permitidas desde el Cliente hacia el Servidor por WebSocket."""

    AUTH = "auth"
    PING = "ping"
    SUBSCRIBE_store = "subscribe_store"


class WSEnvelope(BaseModel):
    """Sobre estándar (Envelope) validado con Pydantic para todos los mensajes salientes."""

    event: WSServerEventType
    timestamp: datetime = Field(default_factory=utc_now)
    room: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class WSClientMessage(BaseModel):
    """Mensaje entrante enviado por el cliente a través del canal WebSocket."""

    type: WSClientActionType
    token: Optional[str] = None
    store_id: Optional[int] = Field(default=None, gt=0)
    client_timestamp: Optional[int] = None
