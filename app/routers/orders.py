"""Router de Pedidos (Orders): creación, consulta aislada por rol, transición de estados y broadcast WS."""

from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import get_client_ip, rate_limiter
from app.core.security import get_current_user, require_roles
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from app.schemas.order import OrderCreate, OrderRead, OrderStatusUpdate
from app.schemas.ws_events import WSServerEventType
from app.services import notification_service, order_service
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/api/orders", tags=["Pedidos"])


def get_order_target_rooms(order: Order) -> list[str]:
    """Devuelve las 3 salas que deben recibir eventos en tiempo real de este pedido."""
    return [
        ws_manager.user_room(order.customer_id),
        ws_manager.store_room(order.store_id),
        ws_manager.admin_room(),
    ]


@router.post(
    "",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_order(
    payload: OrderCreate,
    request: Request,
    customer: Annotated[User, Depends(require_roles(UserRole.CUSTOMER))],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    """Crea un pedido nuevo (solo rol CUSTOMER) y emite el evento 'pedido_creado' en tiempo real."""
    client_ip = get_client_ip(request)
    rate_limiter.check(
        key=f"create_order:{customer.id}:{client_ip}",
        max_requests=settings.RATE_LIMIT_ORDERS_PER_MINUTE,
        window_seconds=60,
    )
    order = order_service.create_order(db, customer=customer, payload=payload)
    order_data = OrderRead.model_validate(order).model_dump(mode="json")

    await ws_manager.broadcast_to_rooms(
        get_order_target_rooms(order),
        event=WSServerEventType.ORDER_CREATED,
        data={"order": order_data},
    )
    await notification_service.notify_order_created(db, order=order)
    return order


@router.get("", response_model=list[OrderRead])
def list_orders(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    store_id: Annotated[int | None, Query(gt=0)] = None,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
) -> list[Order]:
    """Lista pedidos aplicando filtro automático según el rol del usuario autenticado (usado también en resync)."""
    return order_service.list_orders_for_user(
        db,
        user=current_user,
        store_id=store_id,
        status_filter=status_filter,
    )


@router.get("/{order_id}", response_model=OrderRead)
def get_order_detail(
    order_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    """Obtiene el detalle e historial de un pedido validando permisos anti-IDOR."""
    return order_service.get_order_for_user(db, user=current_user, order_id=order_id)


@router.patch("/{order_id}/status", response_model=OrderRead)
async def change_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    """Avanza o cancela un pedido y difunde el evento 'estado_actualizado' por WebSocket."""
    previous_order = order_service.get_order_for_user(db, user=current_user, order_id=order_id)
    previous_status = previous_order.status.value

    order = order_service.update_order_status(
        db,
        actor=current_user,
        order_id=order_id,
        payload=payload,
    )
    order_data = OrderRead.model_validate(order).model_dump(mode="json")

    await ws_manager.broadcast_to_rooms(
        get_order_target_rooms(order),
        event=WSServerEventType.STATUS_UPDATED,
        data={
            "order": order_data,
            "from_status": previous_status,
            "to_status": order.status.value,
            "changed_by_user_id": current_user.id,
            "changed_by_name": current_user.full_name,
        },
    )
    await notification_service.notify_order_status_changed(
        db,
        order=order,
        actor=current_user,
        from_status=previous_status,
        to_status=order.status.value,
    )
    return order
