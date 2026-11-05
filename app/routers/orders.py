"""Router de Pedidos (Orders): creación, consulta aislada por rol y transición de estados."""

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
from app.services import order_service

router = APIRouter(prefix="/api/orders", tags=["Pedidos"])


@router.post(
    "",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
)
def create_new_order(
    payload: OrderCreate,
    request: Request,
    customer: Annotated[User, Depends(require_roles(UserRole.CUSTOMER))],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    """Crea un pedido nuevo (solo rol CUSTOMER).

    - Aplica Rate Limiting por usuario/IP.
    - Calcula el total exclusivamente en el servidor.
    """
    client_ip = get_client_ip(request)
    rate_limiter.check(
        key=f"create_order:{customer.id}:{client_ip}",
        max_requests=settings.RATE_LIMIT_ORDERS_PER_MINUTE,
        window_seconds=60,
    )
    return order_service.create_order(db, customer=customer, payload=payload)


@router.get("", response_model=list[OrderRead])
def list_orders(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    store_id: Annotated[int | None, Query(gt=0)] = None,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
) -> list[Order]:
    """Lista pedidos aplicando filtro automático según el rol del usuario autenticado."""
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
def change_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Order:
    """Avanza o cancela un pedido validando rol, tienda asignada y máquina de estados."""
    return order_service.update_order_status(
        db,
        actor=current_user,
        order_id=order_id,
        payload=payload,
    )
