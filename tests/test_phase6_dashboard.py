"""Pruebas automatizadas de la Fase 6: Dashboard analítico en vivo (REST + WebSockets + RBAC/Anti-IDOR)."""

from decimal import Decimal
from fastapi.testclient import TestClient


def _login_token(client: TestClient, email: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def _receive_until_event(ws, expected_event: str, max_messages: int = 8) -> dict:
    """Extrae tramas del WebSocket hasta encontrar el evento buscado."""
    for _ in range(max_messages):
        msg = ws.receive_json()
        if msg.get("event") == expected_event:
            return msg
    raise AssertionError(f"No llegó el evento '{expected_event}' después de {max_messages} tramas.")


def test_dashboard_rbac_and_anti_idor_isolation(client: TestClient) -> None:
    """Verifica que clientes no accedan al dashboard y que operadores solo vean su sucursal."""
    ana_token = _login_token(client, "ana@cliente.com", "Cliente123!")
    op_centro_token = _login_token(client, "operador.centro@tiendas.com", "Operador123!")
    admin_token = _login_token(client, "admin@tiendas.com", "Admin123!")

    # 1. Un Cliente (CUSTOMER) recibe 403 Forbidden al consultar /api/dashboard
    res_customer = client.get(
        "/api/dashboard",
        headers={"Authorization": f"Bearer {ana_token}"},
    )
    assert res_customer.status_code == 403

    # 2. El Operador de Sucursal Centro (store_id=1) recibe 403 si intenta consultar store_id=2
    res_op_forbidden = client.get(
        "/api/dashboard?store_id=2",
        headers={"Authorization": f"Bearer {op_centro_token}"},
    )
    assert res_op_forbidden.status_code == 403

    # 3. El Operador de Sucursal Centro consulta su propio dashboard -> scope='store', store_id=1
    res_op_ok = client.get(
        "/api/dashboard",
        headers={"Authorization": f"Bearer {op_centro_token}"},
    )
    assert res_op_ok.status_code == 200
    op_data = res_op_ok.json()
    assert op_data["scope"] == "store"
    assert op_data["store_id"] == 1
    assert len(op_data["sales_by_store"]) == 1
    assert op_data["sales_by_store"][0]["store_id"] == 1

    # 4. El Admin consulta el dashboard global -> scope='global', incluye ambas sucursales
    res_admin = client.get(
        "/api/dashboard",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin.status_code == 200
    admin_data = res_admin.json()
    assert admin_data["scope"] == "global"
    assert len(admin_data["sales_by_store"]) == 2


def test_live_dashboard_metrics_and_ws_broadcast(client: TestClient) -> None:
    """Verifica el cálculo exacto de KPIs y la emisión en vivo de 'dashboard_update' por WebSocket."""
    ana_token = _login_token(client, "ana@cliente.com", "Cliente123!")
    op_centro_token = _login_token(client, "operador.centro@tiendas.com", "Operador123!")
    admin_token = _login_token(client, "admin@tiendas.com", "Admin123!")

    ana_headers = {"Authorization": f"Bearer {ana_token}"}
    op_headers = {"Authorization": f"Bearer {op_centro_token}"}

    with (
        client.websocket_connect(f"/ws?token={op_centro_token}") as ws_op,
        client.websocket_connect(f"/ws?token={admin_token}") as ws_admin,
    ):
        assert ws_op.receive_json()["event"] == "connection_established"
        assert ws_admin.receive_json()["event"] == "connection_established"

        # 1. Ana crea un pedido en Sucursal Centro: 2 Hamburguesas ($12.50 c/u) = $25.00
        create_res = client.post(
            "/api/orders",
            headers=ana_headers,
            json={
                "store_id": 1,
                "items": [{"product_id": 1, "quantity": 2}],
            },
        )
        assert create_res.status_code == 201
        order_id = create_res.json()["id"]

        # Tanto el Operador como el Admin reciben 'dashboard_update' por WebSocket
        op_dash_1 = _receive_until_event(ws_op, "dashboard_update")
        assert op_dash_1["data"]["metrics"]["scope"] == "store"
        assert op_dash_1["data"]["metrics"]["store_id"] == 1
        assert op_dash_1["data"]["metrics"]["active_orders_count"] == 1
        assert Decimal(str(op_dash_1["data"]["metrics"]["today_sales_total"])) == Decimal("25.00")
        assert op_dash_1["data"]["metrics"]["orders_by_status"]["RECEIVED"] == 1

        admin_dash_1 = _receive_until_event(ws_admin, "dashboard_update")
        assert admin_dash_1["data"]["metrics"]["scope"] == "global"
        assert admin_dash_1["data"]["metrics"]["active_orders_count"] == 1
        assert Decimal(str(admin_dash_1["data"]["metrics"]["today_sales_total"])) == Decimal("25.00")

        # 2. El Operador avanza el pedido a PREPARING y luego a READY (registra ready_at)
        assert (
            client.patch(
                f"/api/orders/{order_id}/status",
                headers=op_headers,
                json={"status": "PREPARING"},
            ).status_code
            == 200
        )
        _receive_until_event(ws_op, "dashboard_update")

        assert (
            client.patch(
                f"/api/orders/{order_id}/status",
                headers=op_headers,
                json={"status": "READY"},
            ).status_code
            == 200
        )
        op_dash_ready = _receive_until_event(ws_op, "dashboard_update")
        assert op_dash_ready["data"]["metrics"]["orders_by_status"]["READY"] == 1
        assert op_dash_ready["data"]["metrics"]["avg_prep_time_minutes"] >= 0.0

        # 3. El Operador entrega el pedido (DELIVERED) -> active_orders_count baja a 0, ventas siguen en $25.00
        assert (
            client.patch(
                f"/api/orders/{order_id}/status",
                headers=op_headers,
                json={"status": "DELIVERED"},
            ).status_code
            == 200
        )
        op_dash_delivered = _receive_until_event(ws_op, "dashboard_update")
        assert op_dash_delivered["data"]["metrics"]["active_orders_count"] == 0
        assert op_dash_delivered["data"]["metrics"]["orders_by_status"]["DELIVERED"] == 1
        assert Decimal(str(op_dash_delivered["data"]["metrics"]["today_sales_total"])) == Decimal("25.00")
