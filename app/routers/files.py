"""Router de Subida y Descarga Segura de Archivos (Fase 5):
- Imagen de producto (subida exclusiva para ADMIN).
- Comprobante de pago (subida exclusiva para el CUSTOMER dueño del pedido; lectura protegida contra IDOR).
"""

from typing import Annotated
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    bearer_scheme,
    decode_access_token,
    require_roles,
)
from app.models.notification import Notification
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.user import User, UserRole
from app.routers.orders import get_order_target_rooms
from app.schemas.order import OrderRead
from app.schemas.product import ProductRead
from app.schemas.ws_events import WSServerEventType
from app.services import file_service, notification_service, order_service
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/api/files", tags=["Archivos Seguros"])


def _get_user_from_header_or_query(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Query()] = None,
) -> User:
    """Autentica al usuario por cabecera Bearer o por query param ?token=... para descargas seguras."""
    raw_token = credentials.credentials if (credentials and credentials.credentials) else token
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere autenticación para acceder a este archivo.",
        )
    payload = decode_access_token(raw_token)
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inválido o inactivo.",
        )
    return user


@router.post("/products/{product_id}/image", response_model=ProductRead)
async def upload_product_image(
    product_id: int,
    file: Annotated[UploadFile, File(...)],
    _admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> Product:
    """Sube y valida la imagen de un producto del catálogo (exclusivo ADMIN)."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado.",
        )

    filename, _mime = await file_service.validate_and_save_upload(
        file,
        target_dir=file_service.PRODUCTS_UPLOAD_DIR,
        allowed_extensions=file_service.ALLOWED_PRODUCT_IMAGE_EXTENSIONS,
    )

    product.image_path = filename
    db.commit()
    db.refresh(product)
    return product


@router.get("/products/{filename}")
def get_product_image(filename: str) -> FileResponse:
    """Sirve de forma segura la imagen validada de un producto con cabeceras nosniff."""
    file_path, mime_type = file_service.resolve_safe_file_path(
        file_service.PRODUCTS_UPLOAD_DIR,
        filename,
    )
    return FileResponse(
        path=file_path,
        media_type=mime_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.post("/orders/{order_id}/receipt", response_model=OrderRead)
async def upload_order_payment_receipt(
    order_id: int,
    file: Annotated[UploadFile, File(...)],
    customer: Annotated[User, Depends(require_roles(UserRole.CUSTOMER))],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    """Permite al Cliente dueño del pedido subir un comprobante de pago validado (PNG/JPG/WEBP/PDF <= 2 MB)."""
    order = order_service.get_order_for_user(db, user=customer, order_id=order_id)
    if order.status != OrderStatus.RECEIVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede adjuntar comprobante de pago a pedidos en estado RECEIVED.",
        )

    filename, _mime = await file_service.validate_and_save_upload(
        file,
        target_dir=file_service.RECEIPTS_UPLOAD_DIR,
        allowed_extensions=file_service.ALLOWED_RECEIPT_EXTENSIONS,
    )

    order.payment_receipt_path = filename
    db.commit()

    updated_order = order_service.get_order_for_user(db, user=customer, order_id=order_id)
    order_data = OrderRead.model_validate(updated_order).model_dump(mode="json")

    await ws_manager.broadcast_to_rooms(
        get_order_target_rooms(updated_order),
        event=WSServerEventType.STATUS_UPDATED,
        data={
            "order": order_data,
            "from_status": updated_order.status.value,
            "to_status": updated_order.status.value,
            "changed_by_user_id": customer.id,
            "changed_by_name": customer.full_name,
            "receipt_uploaded": True,
        },
    )

    notif = Notification(
        user_id=customer.id,
        order_id=updated_order.id,
        event_type="comprobante_subido",
        title=f"Comprobante recibido (Pedido #{updated_order.id})",
        message="Tu comprobante de pago fue validado y adjuntado correctamente.",
        is_read=False,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    await notification_service._emit_notifications_to_users(db, [notif])

    return updated_order


@router.get("/orders/{order_id}/receipt")
def download_order_payment_receipt(
    order_id: int,
    current_user: Annotated[User, Depends(_get_user_from_header_or_query)],
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    """Sirve el comprobante de pago validando permisos anti-IDOR (solo dueño, operador de esa tienda o admin)."""
    order = order_service.get_order_for_user(db, user=current_user, order_id=order_id)
    if not order.payment_receipt_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Este pedido aún no tiene un comprobante de pago adjunto.",
        )

    file_path, mime_type = file_service.resolve_safe_file_path(
        file_service.RECEIPTS_UPLOAD_DIR,
        order.payment_receipt_path,
    )
    return FileResponse(
        path=file_path,
        media_type=mime_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="{order.payment_receipt_path}"',
            "Cache-Control": "no-store",
        },
    )
