"""Pruebas automatizadas de la Fase 4: Notificaciones persistidas, tiempo real, conteo y Anti-IDOR."""

from fastapi.testclient import TestClient


def _login_token(client: TestClient, email: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_notifications_persisted_and_pushed_via_ws_and_anti_idor(client: TestClient) -> None:
    """Verifica emisión WS de notificaciones, persistencia en BD, marcado como leídas y protección anti-IDOR."""
    ana_token = _login_token(client, "ana@cliente.com", "Cliente123!")
    carlos_token = _login_token(client, "carlos@cliente.com", "Cliente123!")
    op_centro_token = _login_token(client, "operador.centro@tiendas.com", "Operador123!")

    with (
        client.websocket_connect(f"/ws?token={ana_token}") as ws_ana,
        client.websocket_connect(f"/ws?token={op_centro_token}") as ws_op_centro,
    ):
        assert ws_ana.receive_json()["event"] == "connection_established"
        assert ws_op_centro.receive_json()["event"] == "connection_established"

        # 1. Ana crea un pedido en Sucursal Centro
        create_res = client.post(
            "/api/orders",
            headers={"Authorization": f"Bearer {ana_token}"},
            json={
                "store_id": 1,
                "items": [{"product_id": 1, "quantity": 1}],
            },
        )
        assert create_res.status_code == 201
        order_id = create_res.json()["id"]

        # Tanto Ana como el Operador Centro reciben primero 'pedido_creado' y enseguida 'notificacion'
        ana_event_1 = ws_ana.receive_json()
        ana_event_2 = ws_ana.receive_json()
        assert {ana_event_1["event"], ana_event_2["event"]} == {"pedido_creado", "notificacion"}

        op_event_1 = ws_op_centro.receive_json()
        op_event_2 = ws_op_centro.receive_json()
        assert {op_event_1["event"], op_event_2["event"]} == {"pedido_creado", "notificacion"}

        # 2. El Operador avanza el pedido a PREPARING -> Ana recibe notificación en vivo
        patch_res = client.patch(
            f"/api/orders/{order_id}/status",
            headers={"Authorization": f"Bearer {op_centro_token}"},
            json={"status": "PREPARING", "comment": "Cocinando"},
        )
        assert patch_res.status_code == 200

        ana_ev_3 = ws_ana.receive_json()
        ana_ev_4 = ws_ana.receive_json()
        assert {ana_ev_3["event"], ana_ev_4["event"]} == {"estado_actualizado", "notificacion"}

    # 3. Consultamos las notificaciones persistidas de Ana por API REST
    ana_notifs_res = client.get(
        "/api/notifications",
        headers={"Authorization": f"Bearer {ana_token}"},
    )
    assert ana_notifs_res.status_code == 200
    summary = ana_notifs_res.json()
    assert summary["unread_count"] == 2
    assert len(summary["items"]) == 2
    first_notif_id = summary["items"][0]["id"]

    # 4. Anti-IDOR: Carlos intenta marcar como leída una notificación de Ana -> 403 Forbidden
    forbidden_res = client.patch(
        f"/api/notifications/{first_notif_id}/read",
        headers={"Authorization": f"Bearer {carlos_token}"},
    )
    assert forbidden_res.status_code == 403

    # 5. Ana marca su primera notificación como leída -> unread_count baja a 1
    mark_one_res = client.patch(
        f"/api/notifications/{first_notif_id}/read",
        headers={"Authorization": f"Bearer {ana_token}"},
    )
    assert mark_one_res.status_code == 200
    assert mark_one_res.json()["is_read"] is True

    after_one = client.get(
        "/api/notifications",
        headers={"Authorization": f"Bearer {ana_token}"},
    ).json()
    assert after_one["unread_count"] == 1

    # 6. Ana marca todas como leídas -> unread_count baja a 0
    mark_all_res = client.post(
        "/api/notifications/read-all",
        headers={"Authorization": f"Bearer {ana_token}"},
    )
    assert mark_all_res.status_code == 200
    assert mark_all_res.json()["unread_count"] == 0
