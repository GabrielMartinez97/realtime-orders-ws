"""Endpoint WebSocket (/ws) con validación de Origin, autenticación JWT, RBAC en vivo y Heartbeat."""

import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.models.store import Store
from app.models.user import User, UserRole
from app.schemas.ws_events import (
    WSClientActionType,
    WSClientMessage,
    WSServerEventType,
)
from app.websocket.manager import ClientConnection, ws_manager

router = APIRouter(tags=["WebSockets"])


def _is_origin_allowed(origin: str | None) -> bool:
    """Verifica el header Origin para prevenir Cross-Site WebSocket Hijacking (CSWSH).

    - Si el navegador envía Origin, debe coincidir con ALLOWED_ORIGINS (o ser testserver en pytest).
    - Si no se envía Origin (por ejemplo clientes CLI / scripts internos en desarrollo), se permite.
    """
    if not origin:
        return True
    normalized = origin.rstrip("/")
    allowed = {o.rstrip("/") for o in settings.allowed_origins_list}
    allowed.add("http://testserver")
    allowed.add("https://testserver")
    return normalized in allowed


def _authenticate_token(db: Session, token: str) -> User | None:
    """Valida el JWT y recupera el usuario activo desde la base de datos."""
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except Exception:
        return None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


async def _handle_subscribe_store(
    db: Session,
    conn: ClientConnection,
    requested_store_id: int | None,
) -> None:
    """Valida permisos RBAC y anti-IDOR antes de permitir suscribirse al canal de una tienda."""
    if requested_store_id is None:
        await ws_manager.send_personal_event(
            conn,
            event=WSServerEventType.ERROR,
            data={"code": "MISSING_STORE_ID", "message": "Debes indicar un store_id válido."},
        )
        return

    # Validación de permisos en el backend dentro del mensaje WebSocket:
    if conn.role == UserRole.CUSTOMER:
        await ws_manager.send_personal_event(
            conn,
            event=WSServerEventType.ERROR,
            data={
                "code": "FORBIDDEN_ROOM",
                "message": "Acceso denegado: un cliente no puede suscribirse al canal interno de una tienda.",
            },
        )
        return

    if conn.role == UserRole.OPERATOR and conn.store_id != requested_store_id:
        await ws_manager.send_personal_event(
            conn,
            event=WSServerEventType.ERROR,
            data={
                "code": "FORBIDDEN_STORE",
                "message": "Acceso denegado: solo puedes escuchar eventos de tu tienda asignada.",
            },
        )
        return

    store = db.get(Store, requested_store_id)
    if store is None:
        await ws_manager.send_personal_event(
            conn,
            event=WSServerEventType.ERROR,
            data={
                "code": "STORE_NOT_FOUND",
                "message": f"La tienda #{requested_store_id} no existe.",
            },
        )
        return

    room_name = ws_manager.store_room(store.id)
    ws_manager.join_room(conn, room_name)
    await ws_manager.send_personal_event(
        conn,
        event=WSServerEventType.SUBSCRIBED,
        room=room_name,
        data={
            "room": room_name,
            "store_id": store.id,
            "rooms": sorted(conn.rooms),
        },
    )


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = None,
) -> None:
    """Canal WebSocket principal con soporte para autenticación por query param o primer mensaje."""
    origin = websocket.headers.get("origin")
    if not _is_origin_allowed(origin):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Origin no autorizado.",
        )
        return

    await websocket.accept()
    conn: ClientConnection | None = None

    # Usamos el generador get_db() o SessionLocal; para permitir override en pytest
    # resolvemos la dependencia get_db desde websocket.app.dependency_overrides si existe.
    from app.core.database import get_db

    db_provider = websocket.app.dependency_overrides.get(get_db, get_db)
    db_gen = db_provider()
    db: Session = next(db_gen)

    try:
        # Modo 1: Autenticación inmediata por query parameter (?token=...)
        if token:
            user = _authenticate_token(db, token)
            if user is None:
                await websocket.close(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Token JWT inválido o expirado.",
                )
                return
            conn = ws_manager.register(
                websocket,
                user_id=user.id,
                role=user.role,
                store_id=user.store_id,
            )
            await ws_manager.send_personal_event(
                conn,
                event=WSServerEventType.CONNECTION_ESTABLISHED,
                data={
                    "user_id": user.id,
                    "role": user.role.value,
                    "store_id": user.store_id,
                    "rooms": sorted(conn.rooms),
                },
            )

        # Loop principal de recepción de tramas JSON
        while True:
            raw_text = await websocket.receive_text()
            try:
                raw_json: dict[str, Any] = json.loads(raw_text)
                client_msg = WSClientMessage.model_validate(raw_json)
            except (json.JSONDecodeError, ValidationError) as exc:
                if conn is not None:
                    await ws_manager.send_personal_event(
                        conn,
                        event=WSServerEventType.ERROR,
                        data={
                            "code": "INVALID_MESSAGE_FORMAT",
                            "message": "Formato de mensaje WebSocket inválido.",
                            "details": str(exc),
                        },
                    )
                else:
                    await websocket.close(
                        code=status.WS_1008_POLICY_VIOLATION,
                        reason="El primer mensaje debe ser un JSON de autenticación válido.",
                    )
                    return
                continue

            # Modo 2: Autenticación en el primer mensaje {"type": "auth", "token": "..."}
            if conn is None:
                if client_msg.type != WSClientActionType.AUTH or not client_msg.token:
                    await websocket.close(
                        code=status.WS_1008_POLICY_VIOLATION,
                        reason="Debes autenticarte antes de enviar otros mensajes.",
                    )
                    return

                user = _authenticate_token(db, client_msg.token)
                if user is None:
                    await websocket.close(
                        code=status.WS_1008_POLICY_VIOLATION,
                        reason="Token JWT inválido o expirado.",
                    )
                    return

                conn = ws_manager.register(
                    websocket,
                    user_id=user.id,
                    role=user.role,
                    store_id=user.store_id,
                )
                await ws_manager.send_personal_event(
                    conn,
                    event=WSServerEventType.CONNECTION_ESTABLISHED,
                    data={
                        "user_id": user.id,
                        "role": user.role.value,
                        "store_id": user.store_id,
                        "rooms": sorted(conn.rooms),
                    },
                )
                continue

            # A partir de aquí la conexión ya está autenticada
            if client_msg.type == WSClientActionType.PING:
                await ws_manager.send_personal_event(
                    conn,
                    event=WSServerEventType.PONG,
                    data={
                        "client_timestamp": client_msg.client_timestamp,
                        "status": "alive",
                    },
                )
            elif client_msg.type == WSClientActionType.SUBSCRIBE_store:
                await _handle_subscribe_store(db, conn, client_msg.store_id)
            elif client_msg.type == WSClientActionType.AUTH:
                await ws_manager.send_personal_event(
                    conn,
                    event=WSServerEventType.ERROR,
                    data={
                        "code": "ALREADY_AUTHENTICATED",
                        "message": "La conexión ya se encuentra autenticada.",
                    },
                )

    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(conn)
        try:
            next(db_gen)
        except StopIteration:
            pass
