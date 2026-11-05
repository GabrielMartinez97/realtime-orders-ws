"""Router REST de Notificaciones: listado, conteo de no leídas y marcado individual/masivo."""

from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.notification import NotificationRead, NotificationsSummaryRead
from app.services import notification_service

router = APIRouter(prefix="/api/notifications", tags=["Notificaciones"])


@router.get("", response_model=NotificationsSummaryRead)
def get_my_notifications(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> NotificationsSummaryRead:
    """Devuelve las notificaciones persistidas del usuario autenticado y su contador de no leídas."""
    return notification_service.list_user_notifications(
        db,
        user_id=current_user.id,
        limit=limit,
    )


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def mark_single_notification_read(
    notification_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NotificationRead:
    """Marca una notificación específica como leída (con verificación anti-IDOR)."""
    notif = notification_service.mark_notification_as_read(
        db,
        user=current_user,
        notification_id=notification_id,
    )
    return NotificationRead.model_validate(notif)


@router.post("/read-all")
def mark_all_read(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    """Marca todas las notificaciones pendientes del usuario actual como leídas."""
    updated = notification_service.mark_all_notifications_as_read(db, user=current_user)
    return {"updated_count": updated, "unread_count": 0}
