"""Pruebas automatizadas de la Fase 5: Subida y descarga segura de archivos (Magic Bytes, <= 2 MB, UUID y Anti-IDOR)."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.services import file_service

# Cabecera binaria PNG real (89 50 4E 47 0D 0A 1A 0A) + bytes de prueba
VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
# Cabecera binaria PDF real (%PDF-1.7)
VALID_PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
# Ejecutable Windows (MZ) disfrazado
SPOOFED_EXE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"


def _login_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_product_image_upload_validates_role_magic_bytes_and_size(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifica RBAC, rechazo de magic bytes falsificados, límite de 2 MB y nombre UUID aleatorio."""
    monkeypatch.setattr(file_service, "PRODUCTS_UPLOAD_DIR", tmp_path / "products")

    ana_headers = _login_headers(client, "ana@cliente.com", "Cliente123!")
    admin_headers = _login_headers(client, "admin@tiendas.com", "Admin123!")

    # 1. Un Cliente NO puede subir imágenes de productos -> 403 Forbidden
    forbidden_res = client.post(
        "/api/files/products/1/image",
        headers=ana_headers,
        files={"file": ("burger.png", VALID_PNG_BYTES, "image/png")},
    )
    assert forbidden_res.status_code == 403

    # 2. Archivo .exe renombrado a .png (Magic Bytes inválidos) -> 400 Bad Request
    spoof_res = client.post(
        "/api/files/products/1/image",
        headers=admin_headers,
        files={"file": ("malware_renombrado.png", SPOOFED_EXE_BYTES, "image/png")},
    )
    assert spoof_res.status_code == 400
    assert "magic bytes" in spoof_res.json()["detail"].lower()

    # 3. Extensión prohibida (.svg que podría contener XSS) -> 400 Bad Request
    svg_res = client.post(
        "/api/files/products/1/image",
        headers=admin_headers,
        files={"file": ("xss.svg", b"<svg onload=alert(1)></svg>", "image/svg+xml")},
    )
    assert svg_res.status_code == 400

    # 4. Archivo que supera los 2 MB (2 * 1024 * 1024 + 50 bytes) -> 413 Content Too Large
    oversized_bytes = VALID_PNG_BYTES + (b"\x00" * (file_service.MAX_FILE_SIZE_BYTES + 50))
    big_res = client.post(
        "/api/files/products/1/image",
        headers=admin_headers,
        files={"file": ("gigante.png", oversized_bytes, "image/png")},
    )
    assert big_res.status_code == 413

    # 5. Subida válida de imagen PNG real por el Admin -> 200 OK y nombre aleatorio UUID
    ok_res = client.post(
        "/api/files/products/1/image",
        headers=admin_headers,
        files={"file": ("../../intento_traversal.png", VALID_PNG_BYTES, "image/png")},
    )
    assert ok_res.status_code == 200
    saved_name = ok_res.json()["image_path"]
    assert saved_name is not None
    assert "intento_traversal" not in saved_name
    assert saved_name.endswith(".png")
    assert len(saved_name) == 36  # 32 hex chars + ".png"

    # 6. Servir la imagen con cabecera X-Content-Type-Options: nosniff
    get_img = client.get(f"/api/files/products/{saved_name}")
    assert get_img.status_code == 200
    assert get_img.headers["X-Content-Type-Options"] == "nosniff"
    assert get_img.content == VALID_PNG_BYTES


def test_order_receipt_upload_and_anti_idor_download(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifica que solo el cliente dueño suba su comprobante y que la descarga bloquee a otros clientes."""
    monkeypatch.setattr(file_service, "RECEIPTS_UPLOAD_DIR", tmp_path / "receipts")

    ana_headers = _login_headers(client, "ana@cliente.com", "Cliente123!")
    carlos_headers = _login_headers(client, "carlos@cliente.com", "Cliente123!")
    op_centro_headers = _login_headers(client, "operador.centro@tiendas.com", "Operador123!")
    op_norte_headers = _login_headers(client, "operador.norte@tiendas.com", "Operador123!")

    # Ana crea un pedido en Sucursal Centro (store_id=1)
    order_res = client.post(
        "/api/orders",
        headers=ana_headers,
        json={"store_id": 1, "items": [{"product_id": 1, "quantity": 1}]},
    )
    order_id = order_res.json()["id"]

    # Anti-IDOR en subida: Carlos intenta subir un comprobante al pedido de Ana -> 403 Forbidden
    carlos_upload = client.post(
        f"/api/files/orders/{order_id}/receipt",
        headers=carlos_headers,
        files={"file": ("comprobante.pdf", VALID_PDF_BYTES, "application/pdf")},
    )
    assert carlos_upload.status_code == 403

    # Ana sube su comprobante PDF real -> 200 OK
    ana_upload = client.post(
        f"/api/files/orders/{order_id}/receipt",
        headers=ana_headers,
        files={"file": ("mi_transferencia.pdf", VALID_PDF_BYTES, "application/pdf")},
    )
    assert ana_upload.status_code == 200
    assert ana_upload.json()["payment_receipt_path"].endswith(".pdf")

    # Anti-IDOR en descarga:
    # - Carlos (otro cliente) NO puede descargar el comprobante de Ana -> 403
    assert client.get(f"/api/files/orders/{order_id}/receipt", headers=carlos_headers).status_code == 403
    # - Operador de Sucursal Norte (store_id=2) NO puede descargar comprobante de Sucursal Centro -> 403
    assert client.get(f"/api/files/orders/{order_id}/receipt", headers=op_norte_headers).status_code == 403
    # - Operador de Sucursal Centro (store_id=1) SÍ puede verificar el comprobante -> 200 OK
    op_download = client.get(f"/api/files/orders/{order_id}/receipt", headers=op_centro_headers)
    assert op_download.status_code == 200
    assert op_download.content == VALID_PDF_BYTES
