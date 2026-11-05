"""Pruebas automatizadas de la Fase 2: WebSockets autenticados, validación de Origin, salas y broadcast."""

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.schemas.ws_events import WSServerEventType
from app.websocket.manager import ws_manager


def _get_token(client: TestClient, email: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_ws_rejects_unallowed_origin_and_invalid_token(client: TestClient) -> None:
    """Verifica rechazo por Origin malicioso (anti-CSWSH) y por JWT inválido."""
    ana_token = _get_token(client, "ana@cliente.com", "Cliente123!")

    # 1. Origin malicioso -> se cierra con código 1008
    with pytest.raises(WebSocketDisconnect) as exc_origin:
        with client.websocket_connect(
            f"/ws?token={ana_token}",
            headers={"Origin": "https://sitio-atacante.evil"},
        ) as ws:
            ws.receive_json()
    assert exc_origin.value.code == 1008

    # 2. Token inválido -> se cierra con código 1008
    with pytest.raises(WebSocketDisconnect) as exc_token:
        with client.websocket_connect("/ws?token=token.falso.manipulado") as ws:
            ws.receive_json()
    assert exc_token.value.code == 1008


def test_ws_auth_by_first_message_and_heartbeat(client: TestClient) -> None:
    """Verifica autenticación mediante el primer mensaje JSON y el ciclo de Heartbeat ping/pong."""
    ana_token = _get_token(client, "ana@cliente.com", "Cliente123!")

    with client.websocket_connect("/ws") as ws:
        # Enviamos primer mensaje de autenticación
        ws.send_json({"type": "auth", "token": ana_token})
        established = ws.receive_json()
        assert established["event"] == "connection_established"
        assert established["data"]["role"] == "CUSTOMER"
        user_id = established["data"]["user_id"]
        assert established["data"]["rooms"] == [f"user:{user_id}"]

        # Enviamos heartbeat ping -> recibimos pong
        ws.send_json({"type": "ping", "client_timestamp": 1700000000})
        pong = ws.receive_json()
        assert pong["event"] == "pong"
        assert pong["data"]["client_timestamp"] == 1700000000
        assert pong["data"]["status"] == "alive"


def test_ws_room_permissions_and_isolated_broadcast(client: TestClient) -> None:
    """Verifica que los permisos se validen dentro de los mensajes WS y que el broadcast respete las salas."""
    ana_token = _get_token(client, "ana@cliente.com", "Cliente123!")
    op_centro_token = _get_token(client, "operador.centro@tiendas.com", "Operador123!")
    op_norte_token = _get_token(client, "operador.norte@tiendas.com", "Operador123!")
    admin_token = _get_token(client, "admin@tiendas.com", "Admin123!")

    with (
        client.websocket_connect(f"/ws?token={ana_token}") as ws_ana,
        client.websocket_connect(f"/ws?token={op_centro_token}") as ws_op_centro,
        client.websocket_connect(f"/ws?token={op_norte_token}") as ws_op_norte,
        client.websocket_connect(f"/ws?token={admin_token}") as ws_admin,
    ):
        ana_hello = ws_ana.receive_json()
        op_centro_hello = ws_op_centro.receive_json()
        op_norte_hello = ws_op_norte.receive_json()
        admin_hello = ws_admin.receive_json()

        assert "store:1" in op_centro_hello["data"]["rooms"]
        assert "store:2" in op_norte_hello["data"]["rooms"]
        assert "admin:global" in admin_hello["data"]["rooms"]

        # 1. Cliente (Ana) intenta suscribirse al canal de la Tienda 1 -> Error FORBIDDEN_ROOM
        ws_ana.send_json({"type": "subscribe_store", "store_id": 1})
        ana_err = ws_ana.receive_json()
        assert ana_err["event"] == "error"
        assert ana_err["data"]["code"] == "FORBIDDEN_ROOM"

        # 2. Operador de Tienda 1 intenta espiar Tienda 2 -> Error FORBIDDEN_STORE
        ws_op_centro.send_json({"type": "subscribe_store", "store_id": 2})
        op_err = ws_op_centro.receive_json()
        assert op_err["event"] == "error"
        assert op_err["data"]["code"] == "FORBIDDEN_STORE"

        # 3. Admin se suscribe a Tienda 1 -> Éxito
        ws_admin.send_json({"type": "subscribe_store", "store_id": 1})
        admin_sub = ws_admin.receive_json()
        assert admin_sub["event"] == "subscribed"
        assert "store:1" in admin_sub["data"]["rooms"]

        # 4. Broadcast a ['store:1', 'admin:global']:
        # - Debe llegar a op_centro (en store:1) y a admin (solo 1 vez aunque esté en store:1 y admin:global).
        # - NO debe llegar a op_norte ni a ana.
        delivered = anyio.run(
            ws_manager.broadcast_to_rooms,
            ["store:1", "admin:global"],
            WSServerEventType.ORDER_CREATED,
            {"order_id": 999, "store_id": 1},
        )
        assert delivered == 2

        msg_op_centro = ws_op_centro.receive_json()
        assert msg_op_centro["event"] == "pedido_creado"
        assert msg_op_centro["data"]["order_id"] == 999

        msg_admin = ws_admin.receive_json()
        assert msg_admin["event"] == "pedido_creado"
        assert msg_admin["data"]["order_id"] == 999

    # Al salir del bloque with, todas las conexiones se limpiaron del ConnectionManager
    assert ws_manager.active_connections_count == 0
