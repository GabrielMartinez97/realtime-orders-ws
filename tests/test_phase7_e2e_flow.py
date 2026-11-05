"""Pruebas de integración de extremo a extremo (E2E - Fase 7): ciclo completo de vida del pedido."""

from decimal import Decimal
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.services import file_service

VALID_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"


def _login(client: TestClient, email: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_complete_end_to_end_order_lifecycle(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valida el flujo completo: Admin sube foto -> Cliente pide y adjunta pago -> Operador despacha -> Dashboard y Auditoría."""
    monkeypatch.setattr(file_service, "PRODUCTS_UPLOAD_DIR", tmp_path / "products")
    monkeypatch.setattr(file_service, "RECEIPTS_UPLOAD_DIR", tmp_path / "receipts")

    # 1. Healthcheck de producción
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    admin_token = _login(client, "admin@tiendas.com", "Admin123!")
    op_token = _login(client, "operador.centro@tiendas.com", "Operador123!")
    customer_token = _login(client, "ana@cliente.com", "Cliente123!")

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    op_headers = {"Authorization": f"Bearer {op_token}"}
    customer_headers = {"Authorization": f"Bearer {customer_token}"}

    # 2. Admin sube imagen verificada por Magic Bytes al producto #1
    img_res = client.post(
        "/api/files/products/1/image",
        headers=admin_headers,
        files={"file": ("smash.png", VALID_PNG, "image/png")},
    )
    assert img_res.status_code == 200

    # 3. Cliente crea pedido en Sucursal Centro (1 Hamburguesa $12.50 + 2 Papas $4.75 = $22.00)
    order_res = client.post(
        "/api/orders",
        headers=customer_headers,
        json={
            "store_id": 1,
            "notes": "Sin pepinillos",
            "items": [
                {"product_id": 1, "quantity": 1},
                {"product_id": 2, "quantity": 2},
            ],
        },
    )
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]
    assert Decimal(str(order_res.json()["total_amount"])) == Decimal("22.00")

    # 4. Cliente sube su comprobante de pago
    receipt_res = client.post(
        f"/api/files/orders/{order_id}/receipt",
        headers=customer_headers,
        files={"file": ("pago.png", VALID_PNG, "image/png")},
    )
    assert receipt_res.status_code == 200

    # 5. Operador avanza el pedido por toda la máquina de estados: RECEIVED -> PREPARING -> READY -> DELIVERED
    for next_status in ("PREPARING", "READY", "DELIVERED"):
        st_res = client.patch(
            f"/api/orders/{order_id}/status",
            headers=op_headers,
            json={"status": next_status, "comment": f"Paso a {next_status}"},
        )
        assert st_res.status_code == 200
        assert st_res.json()["status"] == next_status

    # 6. Verificar auditoría completa (4 eventos: creación + 3 transiciones) y ready_at registrado
    detail_res = client.get(f"/api/orders/{order_id}", headers=customer_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["ready_at"] is not None
    assert len(detail["status_history"]) == 4

    # 7. Verificar Dashboard consolidado del Admin y buzón de notificaciones del Cliente
    dash_res = client.get("/api/dashboard", headers=admin_headers)
    assert dash_res.status_code == 200
    dash = dash_res.json()
    assert dash["active_orders_count"] == 0
    assert dash["orders_by_status"]["DELIVERED"] == 1
    assert Decimal(str(dash["today_sales_total"])) == Decimal("22.00")

    notif_res = client.get("/api/notifications", headers=customer_headers)
    assert notif_res.status_code == 200
    assert notif_res.json()["unread_count"] == 5
