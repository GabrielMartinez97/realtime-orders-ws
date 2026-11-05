"""Servicio de cálculo y difusión en tiempo real de métricas del Dashboard (Fase 6)."""

from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from app.models.store import Store
from app.models.user import User, UserRole
from app.schemas.dashboard import DashboardMetrics, StoreSalesItem
from app.schemas.ws_events import WSServerEventType
from app.websocket.manager import ws_manager

ACTIVE_STATUSES: set[OrderStatus] = {
    OrderStatus.RECEIVED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
}


def _ensure_utc(dt: datetime) -> datetime:
    """Normaliza un datetime (con o sin tzinfo de SQLite) a UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _start_of_utc_day() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def compute_dashboard_metrics(
    db: Session,
    *,
    store_id: int | None = None,
) -> DashboardMetrics:
    """Calcula KPIs y series analíticas desde SQL (filtrado por tienda o global)."""
    store_name: str | None = None
    if store_id is not None:
        store = db.get(Store, store_id)
        if store is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"La tienda #{store_id} no existe.",
            )
        store_name = store.name

    # 1. Conteo de pedidos agrupado por estado (siempre incluye las 5 claves con 0 por defecto)
    orders_by_status: dict[str, int] = {st.value: 0 for st in OrderStatus}
    status_stmt = select(Order.status, func.count(Order.id)).group_by(Order.status)
    if store_id is not None:
        status_stmt = status_stmt.where(Order.store_id == store_id)

    for order_status, count_val in db.execute(status_stmt).all():
        key = order_status.value if isinstance(order_status, OrderStatus) else str(order_status)
        orders_by_status[key] = int(count_val)

    active_orders_count = sum(orders_by_status[st.value] for st in ACTIVE_STATUSES)
    total_orders_count = sum(orders_by_status.values())

    # 2. Ventas del día actual (UTC) excluyendo pedidos CANCELLED
    start_of_day = _start_of_utc_day()
    sales_stmt = select(func.coalesce(func.sum(Order.total_amount), 0)).where(
        Order.status != OrderStatus.CANCELLED,
        Order.created_at >= start_of_day,
    )
    if store_id is not None:
        sales_stmt = sales_stmt.where(Order.store_id == store_id)

    raw_sales = db.scalar(sales_stmt) or 0
    today_sales_total = Decimal(str(raw_sales)).quantize(Decimal("0.01"))

    # 3. Tiempo promedio de preparación en minutos (created_at -> ready_at)
    prep_stmt = select(Order.created_at, Order.ready_at).where(
        Order.ready_at.is_not(None),
        Order.status != OrderStatus.CANCELLED,
    )
    if store_id is not None:
        prep_stmt = prep_stmt.where(Order.store_id == store_id)

    prep_rows = db.execute(prep_stmt).all()
    if prep_rows:
        durations_minutes: list[float] = []
        for created_dt, ready_dt in prep_rows:
            if created_dt is not None and ready_dt is not None:
                diff_seconds = (_ensure_utc(ready_dt) - _ensure_utc(created_dt)).total_seconds()
                durations_minutes.append(max(0.0, diff_seconds / 60.0))
        avg_prep_time_minutes = (
            round(sum(durations_minutes) / len(durations_minutes), 2)
            if durations_minutes
            else 0.0
        )
    else:
        avg_prep_time_minutes = 0.0

    # 4. Desglose por sucursal (respetando aislamiento si store_id está fijado)
    stores_stmt = select(Store).order_by(Store.id.asc())
    if store_id is not None:
        stores_stmt = stores_stmt.where(Store.id == store_id)
    stores_list = list(db.scalars(stores_stmt).all())

    sales_by_store: list[StoreSalesItem] = []
    for st in stores_list:
        st_active = (
            db.scalar(
                select(func.count(Order.id)).where(
                    Order.store_id == st.id,
                    Order.status.in_(ACTIVE_STATUSES),
                )
            )
            or 0
        )
        st_total = (
            db.scalar(select(func.count(Order.id)).where(Order.store_id == st.id)) or 0
        )
        st_sales_raw = (
            db.scalar(
                select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                    Order.store_id == st.id,
                    Order.status != OrderStatus.CANCELLED,
                    Order.created_at >= start_of_day,
                )
            )
            or 0
        )
        sales_by_store.append(
            StoreSalesItem(
                store_id=st.id,
                store_name=st.name,
                active_orders_count=int(st_active),
                total_orders_count=int(st_total),
                today_sales_total=Decimal(str(st_sales_raw)).quantize(Decimal("0.01")),
            )
        )

    return DashboardMetrics(
        scope="store" if store_id is not None else "global",
        store_id=store_id,
        store_name=store_name,
        active_orders_count=active_orders_count,
        total_orders_count=total_orders_count,
        today_sales_total=today_sales_total,
        avg_prep_time_minutes=avg_prep_time_minutes,
        orders_by_status=orders_by_status,
        sales_by_store=sales_by_store,
    )


def get_dashboard_for_user(
    db: Session,
    *,
    user: User,
    requested_store_id: int | None = None,
) -> DashboardMetrics:
    """Valida RBAC y anti-IDOR antes de calcular las métricas del dashboard."""
    if user.role == UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: el dashboard analítico es exclusivo para operadores y administradores.",
        )

    if user.role == UserRole.OPERATOR:
        if user.store_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El operador no tiene una tienda asignada.",
            )
        if requested_store_id is not None and requested_store_id != user.store_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado: no puedes consultar métricas de otra sucursal.",
            )
        return compute_dashboard_metrics(db, store_id=user.store_id)

    # Rol ADMIN: puede ver global (store_id=None) o filtrar por una tienda específica
    return compute_dashboard_metrics(db, store_id=requested_store_id)


async def broadcast_dashboard_update(db: Session, *, store_id: int) -> None:
    """Recalcula y emite 'dashboard_update' a la sala de la tienda y a la sala global de Admin."""
    store_metrics = compute_dashboard_metrics(db, store_id=store_id).model_dump(mode="json")
    global_metrics = compute_dashboard_metrics(db, store_id=None).model_dump(mode="json")

    await ws_manager.broadcast_to_room(
        ws_manager.store_room(store_id),
        event=WSServerEventType.DASHBOARD_UPDATE,
        data={
            "affected_store_id": store_id,
            "metrics": store_metrics,
        },
    )
    await ws_manager.broadcast_to_room(
        ws_manager.admin_room(),
        event=WSServerEventType.DASHBOARD_UPDATE,
        data={
            "affected_store_id": store_id,
            "metrics": global_metrics,
            "store_metrics": store_metrics,
        },
    )
