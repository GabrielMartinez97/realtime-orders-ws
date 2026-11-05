"""Endpoint WebSocket (/ws) con validación de Origin, autenticación JWT, RBAC en vivo y Heartbeat."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.models.store import Store
from app.models.user import User, UserRole
from app.schemas.order import OrderRead, OrderStatusUpdate
from app.schemas.ws_events import (
    WSClientActionType,
    WSClientMessage,
    WSServerEventType,
)
from app.services import dashboard_service, notification_service, order_service
from app.websocket.manager import ClientConnection, ws_manager

router = APIRouter(tags=["WebSockets"])


def _is_origin_allowed(origin: str | None) -> bool:
    """Verifica el header Origin para prevenir Cross-Site WebSocket Hijacking (CSWSH)."""
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


async def _handle_ws_update_order_status(
    db: Session,
    conn: ClientConnection,
    msg: WSClientMessage,
) -> None:
    """Permite cambiar el estado de un pedido por WebSocket validando RBAC y anti-IDOR en el backend."""
    if msg.order_id is None or msg.status is None:
        await ws_manager.send_personal_event(
            conn,
            event=WSServerEventType.ERROR,
            data={
                "code": "MISSING_FIELDS",
                "message": "Para actualizar un pedido debes enviar order_id y status.",
            },
        )
        return

    actor = db.get(User, conn.user_id)
    if actor is None or not actor.is_active:
        await ws_manager.send_personal_event(
            conn,
            event=WSServerEventType.ERROR,
            data={"code": "UNAUTHORIZED", "message": "Usuario inactivo o no encontrado."},
        )
        return

    try:
        existing = order_service.get_order_for_user(db, user=actor, order_id=msg.order_id)
        previous_status = existing.status.value
        updated_order = order_service.update_order_status(
            db,
            actor=actor,
            order_id=msg.order_id,
            payload=OrderStatusUpdate(status=msg.status, comment=msg.comment),
        )
    except HTTPException as exc:
        code = "FORBIDDEN_ACTION" if exc.status_code == status.HTTP_403_FORBIDDEN else "UPDATE_REJECTED"
        await ws_manager.send_personal_event(
            conn,
            event=WSServerEventType.ERROR,
            data={"code": code, "message": str(exc.detail)},
        )
        return

    order_data = OrderRead.model_validate(updated_order).model_dump(mode="json")
    target_rooms = [
        ws_manager.user_room(updated_order.customer_id),
        ws_manager.store_room(updated_order.store_id),
        ws_manager.admin_room(),
    ]
    await ws_manager.broadcast_to_rooms(
        target_rooms,
        event=WSServerEventType.STATUS_UPDATED,
        data={
            "order": order_data,
            "from_status": previous_status,
            "to_status": updated_order.status.value,
            "changed_by_user_id": actor.id,
            "changed_by_name": actor.full_name,
        },
    )
    await notification_service.notify_order_status_changed(
        db,
        order=updated_order,
        actor=actor,
        from_status=previous_status,
        to_status=updated_order.status.value,
    )
    await dashboard_service.broadcast_dashboard_update(db, store_id=updated_order.store_id)


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

            # Mensajes de clientes autenticados
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
            elif client_msg.type == WSClientActionType.UPDATE_ORDER_STATUS:
                await _handle_ws_update_order_status(db, conn, client_msg)
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
