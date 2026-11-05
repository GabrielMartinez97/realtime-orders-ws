"""Pruebas automatizadas de la Fase 3: Flujo de pedidos en vivo (REST + WebSockets en tiempo real)."""

from fastapi.testclient import TestClient


def _login_token(client: TestClient, email: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def _receive_until_event(ws, expected_event: str, max_messages: int = 5) -> dict:
    """Lee tramas del WebSocket hasta encontrar el tipo de evento esperado."""
    for _ in range(max_messages):
        msg = ws.receive_json()
        if msg.get("event") == expected_event:
            return msg
    raise AssertionError(f"No se recibió el evento '{expected_event}' tras {max_messages} mensajes.")


def test_live_order_creation_and_status_broadcast_across_roles(client: TestClient) -> None:
    """Verifica que al crear un pedido y cambiar su estado, los eventos lleguen en vivo a las salas correctas."""
    ana_token = _login_token(client, "ana@cliente.com", "Cliente123!")
    op_centro_token = _login_token(client, "operador.centro@tiendas.com", "Operador123!")
    admin_token = _login_token(client, "admin@tiendas.com", "Admin123!")

    with (
        client.websocket_connect(f"/ws?token={ana_token}") as ws_ana,
        client.websocket_connect(f"/ws?token={op_centro_token}") as ws_op_centro,
        client.websocket_connect(f"/ws?token={admin_token}") as ws_admin,
    ):
        assert ws_ana.receive_json()["event"] == "connection_established"
        assert ws_op_centro.receive_json()["event"] == "connection_established"
        assert ws_admin.receive_json()["event"] == "connection_established"

        # 1. Ana crea un pedido en Sucursal Centro (store_id=1) vía API REST
        create_res = client.post(
            "/api/orders",
            headers={"Authorization": f"Bearer {ana_token}"},
            json={
                "store_id": 1,
                "notes": "Pedido en tiempo real",
                "items": [{"product_id": 1, "quantity": 1}],
            },
        )
        assert create_res.status_code == 201
        order_id = create_res.json()["id"]

        # 2. Los 3 conectados (Ana, Operador Centro y Admin) reciben 'pedido_creado' al instante
        for ws in (ws_ana, ws_op_centro, ws_admin):
            event_msg = _receive_until_event(ws, "pedido_creado")
            assert event_msg["data"]["order"]["id"] == order_id
            assert event_msg["data"]["order"]["status"] == "RECEIVED"

        # 3. El Operador de Sucursal Centro cambia el estado a PREPARING enviando mensaje WebSocket
        ws_op_centro.send_json(
            {
                "type": "update_order_status",
                "order_id": order_id,
                "status": "PREPARING",
                "comment": "En cocina",
            }
        )

        # 4. Los 3 reciben 'estado_actualizado' en vivo con from_status='RECEIVED' y to_status='PREPARING'
        for ws in (ws_ana, ws_op_centro, ws_admin):
            status_msg = _receive_until_event(ws, "estado_actualizado")
            assert status_msg["data"]["order"]["id"] == order_id
            assert status_msg["data"]["from_status"] == "RECEIVED"
            assert status_msg["data"]["to_status"] == "PREPARING"


def test_ws_update_order_status_enforces_anti_idor(client: TestClient) -> None:
    """Verifica que un operador de otra tienda NO pueda cambiar el estado de un pedido por WebSocket."""
    ana_token = _login_token(client, "ana@cliente.com", "Cliente123!")
    op_norte_token = _login_token(client, "operador.norte@tiendas.com", "Operador123!")

    create_res = client.post(
        "/api/orders",
        headers={"Authorization": f"Bearer {ana_token}"},
        json={
            "store_id": 1,
            "items": [{"product_id": 1, "quantity": 1}],
        },
    )
    order_id = create_res.json()["id"]

    with client.websocket_connect(f"/ws?token={op_norte_token}") as ws_op_norte:
        assert ws_op_norte.receive_json()["event"] == "connection_established"

        ws_op_norte.send_json(
            {
                "type": "update_order_status",
                "order_id": order_id,
                "status": "PREPARING",
            }
        )
        err_msg = _receive_until_event(ws_op_norte, "error")
        assert err_msg["data"]["code"] == "FORBIDDEN_ACTION"
