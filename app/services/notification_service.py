"""Servicio de Notificaciones: persistencia en BD, conteo de no leídas, Anti-IDOR y envío WS."""

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from app.schemas.notification import NotificationRead, NotificationsSummaryRead
from app.schemas.ws_events import WSServerEventType
from app.websocket.manager import ws_manager

STATUS_SPANISH = {
    OrderStatus.RECEIVED.value: "Recibido",
    OrderStatus.PREPARING.value: "Preparando",
    OrderStatus.READY.value: "Listo para retirar",
    OrderStatus.DELIVERED.value: "Entregado",
    OrderStatus.CANCELLED.value: "Cancelado",
}


def get_unread_count(db: Session, user_id: int) -> int:
    """Calcula la cantidad exacta de notificaciones no leídas de un usuario."""
    stmt = (
        select(func.count(Notification.id))
        .where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
    )
    return int(db.scalar(stmt) or 0)


def list_user_notifications(
    db: Session,
    *,
    user_id: int,
    limit: int = 30,
) -> NotificationsSummaryRead:
    """Devuelve las notificaciones más recientes del usuario junto con el total de no leídas."""
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    items = list(db.scalars(stmt).all())
    unread = get_unread_count(db, user_id)
    return NotificationsSummaryRead(
        unread_count=unread,
        items=[NotificationRead.model_validate(n) for n in items],
    )


def mark_notification_as_read(
    db: Session,
    *,
    user: User,
    notification_id: int,
) -> Notification:
    """Marca una notificación como leída verificando que pertenezca al usuario autenticado (Anti-IDOR)."""
    notif = db.get(Notification, notification_id)
    if notif is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificación no encontrada.",
        )

    if notif.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: no puedes modificar notificaciones de otro usuario.",
        )

    if not notif.is_read:
        notif.is_read = True
        db.commit()
        db.refresh(notif)

    return notif


def mark_all_notifications_as_read(db: Session, *, user: User) -> int:
    """Marca como leídas todas las notificaciones pendientes del usuario actual."""
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    result = db.execute(stmt)
    db.commit()
    return int(result.rowcount or 0)


async def _emit_notifications_to_users(
    db: Session,
    notifications: list[Notification],
) -> None:
    """Envía por WebSocket cada notificación recién persistida a la sala privada de su destinatario."""
    for notif in notifications:
        unread = get_unread_count(db, notif.user_id)
        payload = {
            "notification": NotificationRead.model_validate(notif).model_dump(mode="json"),
            "unread_count": unread,
        }
        await ws_manager.broadcast_to_room(
            ws_manager.user_room(notif.user_id),
            event=WSServerEventType.NOTIFICATION,
            data=payload,
        )


async def notify_order_created(db: Session, *, order: Order) -> list[Notification]:
    """Crea y persiste notificaciones al registrarse un nuevo pedido y las emite en vivo."""
    created_notifs: list[Notification] = []

    # 1. Notificación de confirmación para el Cliente
    customer_notif = Notification(
        user_id=order.customer_id,
        order_id=order.id,
        event_type="pedido_creado",
        title=f"Pedido #{order.id} registrado",
        message=f"Tu pedido por ${order.total_amount} fue recibido correctamente.",
        is_read=False,
    )
    db.add(customer_notif)
    created_notifs.append(customer_notif)

    # 2. Notificaciones para los Operadores de ESA tienda y Administradores activos
    staff_stmt = select(User).where(
        User.is_active.is_(True),
        (
            (User.role == UserRole.ADMIN)
            | ((User.role == UserRole.OPERATOR) & (User.store_id == order.store_id))
        ),
    )
    staff_users = list(db.scalars(staff_stmt).all())
    for staff in staff_users:
        staff_notif = Notification(
            user_id=staff.id,
            order_id=order.id,
            event_type="pedido_creado",
            title=f"Nuevo Pedido #{order.id}",
            message=f"Ingreso un pedido nuevo por ${order.total_amount} en la tienda #{order.store_id}.",
            is_read=False,
        )
        db.add(staff_notif)
        created_notifs.append(staff_notif)

    db.commit()
    for n in created_notifs:
        db.refresh(n)

    await _emit_notifications_to_users(db, created_notifs)
    return created_notifs


async def notify_order_status_changed(
    db: Session,
    *,
    order: Order,
    actor: User,
    from_status: str,
    to_status: str,
) -> list[Notification]:
    """Persiste y emite notificaciones cuando cambia el estado de un pedido."""
    created_notifs: list[Notification] = []
    friendly_to = STATUS_SPANISH.get(to_status, to_status)
    friendly_from = STATUS_SPANISH.get(from_status, from_status)

    # Si el cambio lo realizó personal de tienda/admin, notificamos al Cliente dueño del pedido
    if actor.id != order.customer_id:
        cust_notif = Notification(
            user_id=order.customer_id,
            order_id=order.id,
            event_type="estado_actualizado",
            title=f"Pedido #{order.id}: {friendly_to}",
            message=f"Tu pedido pasó de '{friendly_from}' a '{friendly_to}'.",
            is_read=False,
        )
        db.add(cust_notif)
        created_notifs.append(cust_notif)
    else:
        # Si el propio cliente canceló su pedido, notificamos a los operadores de la tienda y admins
        staff_stmt = select(User).where(
            User.is_active.is_(True),
            (
                (User.role == UserRole.ADMIN)
                | ((User.role == UserRole.OPERATOR) & (User.store_id == order.store_id))
            ),
        )
        for staff in db.scalars(staff_stmt).all():
            staff_notif = Notification(
                user_id=staff.id,
                order_id=order.id,
                event_type="estado_actualizado",
                title=f"Pedido #{order.id} cancelado por cliente",
                message=f"El cliente canceló el pedido #{order.id}.",
                is_read=False,
            )
            db.add(staff_notif)
            created_notifs.append(staff_notif)

    db.commit()
    for n in created_notifs:
        db.refresh(n)

    await _emit_notifications_to_users(db, created_notifs)
    return created_notifs
