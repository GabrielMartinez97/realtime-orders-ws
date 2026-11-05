"""Pruebas automatizadas de la Fase 1: Autenticación JWT, RBAC, Anti-IDOR y Máquina de Estados."""

from fastapi.testclient import TestClient


def _login_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_security_headers_and_login_flow(client: TestClient) -> None:
    """Verifica cabeceras de seguridad, login exitoso y rechazo de contraseña incorrecta."""
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["X-Frame-Options"] == "DENY"

    # Contraseña incorrecta -> 401
    bad_res = client.post(
        "/api/auth/login",
        json={"email": "ana@cliente.com", "password": "WrongPassword123"},
    )
    assert bad_res.status_code == 401

    # Login correcto -> 200 con JWT y rol CUSTOMER
    ok_res = client.post(
        "/api/auth/login",
        json={"email": "ana@cliente.com", "password": "Cliente123!"},
    )
    assert ok_res.status_code == 200
    data = ok_res.json()
    assert "access_token" in data
    assert data["user"]["role"] == "CUSTOMER"


def test_login_rate_limiting(client: TestClient) -> None:
    """Verifica que tras exceder el límite de intentos por minuto se responda HTTP 429."""
    for _ in range(5):
        res = client.post(
            "/api/auth/login",
            json={"email": "ana@cliente.com", "password": "badpassword"},
        )
        assert res.status_code == 401

    sixth = client.post(
        "/api/auth/login",
        json={"email": "ana@cliente.com", "password": "badpassword"},
    )
    assert sixth.status_code == 429
    assert "Retry-After" in sixth.headers


def test_rbac_catalog_protection(client: TestClient) -> None:
    """Verifica que ni un Cliente ni un Operador puedan crear productos, pero el Admin sí."""
    customer_headers = _login_headers(client, "ana@cliente.com", "Cliente123!")
    operator_headers = _login_headers(client, "operador.centro@tiendas.com", "Operador123!")
    admin_headers = _login_headers(client, "admin@tiendas.com", "Admin123!")

    product_payload = {
        "store_id": 1,
        "name": "Postre Especial",
        "description": "Cheesecake de frutos rojos",
        "price": "6.50",
        "is_available": True,
    }

    assert client.post("/api/products", json=product_payload, headers=customer_headers).status_code == 403
    assert client.post("/api/products", json=product_payload, headers=operator_headers).status_code == 403

    admin_res = client.post("/api/products", json=product_payload, headers=admin_headers)
    assert admin_res.status_code == 201
    assert admin_res.json()["price"] == "6.50"


def test_server_side_total_snapshot_and_anti_idor(client: TestClient) -> None:
    """Verifica cálculo de total en servidor, snapshot de precios y aislamiento anti-IDOR entre clientes y tiendas."""
    ana_headers = _login_headers(client, "ana@cliente.com", "Cliente123!")
    carlos_headers = _login_headers(client, "carlos@cliente.com", "Cliente123!")
    op_centro_headers = _login_headers(client, "operador.centro@tiendas.com", "Operador123!")
    op_norte_headers = _login_headers(client, "operador.norte@tiendas.com", "Operador123!")
    admin_headers = _login_headers(client, "admin@tiendas.com", "Admin123!")

    # Ana crea un pedido en Sucursal Centro (store_id=1):
    # Producto 1 ($12.50) x 2 = $25.00 + Producto 2 ($4.75) x 1 = $4.75 -> Total esperado: $29.75
    create_res = client.post(
        "/api/orders",
        headers=ana_headers,
        json={
            "store_id": 1,
            "notes": "Sin cebolla por favor",
            "items": [
                {"product_id": 1, "quantity": 2},
                {"product_id": 2, "quantity": 1},
            ],
        },
    )
    assert create_res.status_code == 201, create_res.text
    order = create_res.json()
    order_id = order["id"]
    assert order["total_amount"] == "29.75"
    assert order["status"] == "RECEIVED"
    assert len(order["status_history"]) == 1

    # Si el Admin sube el precio del Producto 1 a $20.00, el pedido ya creado NO debe cambiar su total
    patch_prod = client.patch(
        "/api/products/1",
        headers=admin_headers,
        json={"price": "20.00"},
    )
    assert patch_prod.status_code == 200

    order_after_price_change = client.get(f"/api/orders/{order_id}", headers=ana_headers).json()
    assert order_after_price_change["total_amount"] == "29.75"

    # Anti-IDOR 1: Carlos (otro cliente) intenta ver el pedido de Ana -> 403 Forbidden
    carlos_view = client.get(f"/api/orders/{order_id}", headers=carlos_headers)
    assert carlos_view.status_code == 403

    # Anti-IDOR 2: Operador de Sucursal Norte (store_id=2) intenta ver o cambiar pedido de Sucursal Centro (store_id=1) -> 403
    assert client.get(f"/api/orders/{order_id}", headers=op_norte_headers).status_code == 403
    assert (
        client.patch(
            f"/api/orders/{order_id}/status",
            headers=op_norte_headers,
            json={"status": "PREPARING"},
        ).status_code
        == 403
    )

    # Flujo válido de máquina de estados por Operador de Sucursal Centro:
    # Intentar saltar directo de RECEIVED a DELIVERED debe fallar (400 Bad Request)
    invalid_jump = client.patch(
        f"/api/orders/{order_id}/status",
        headers=op_centro_headers,
        json={"status": "DELIVERED"},
    )
    assert invalid_jump.status_code == 400

    # Transiciones válidas: RECEIVED -> PREPARING -> READY -> DELIVERED
    for next_status in ("PREPARING", "READY", "DELIVERED"):
        step_res = client.patch(
            f"/api/orders/{order_id}/status",
            headers=op_centro_headers,
            json={"status": next_status, "comment": f"Avanzando a {next_status}"},
        )
        assert step_res.status_code == 200
        assert step_res.json()["status"] == next_status

    final_order = client.get(f"/api/orders/{order_id}", headers=ana_headers).json()
    assert final_order["ready_at"] is not None
    assert len(final_order["status_history"]) == 4
