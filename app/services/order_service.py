"""Servicio de Lógica de Negocio para Pedidos (Orders).

Centraliza:
1. Creación de pedidos con cálculo de total 100% en el servidor (Decimal).
2. Patrón Snapshot en OrderItems para preservar precios históricos.
3. Control de acceso por recurso (Anti-IDOR) para Clientes, Operadores y Admins.
4. Máquina de estados estricta y registro de auditoría en OrderStatusHistory.
"""

from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.order import (
    VALID_STATUS_TRANSITIONS,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
)
from app.models.product import Product
from app.models.store import Store
from app.models.user import User, UserRole
from app.schemas.order import OrderCreate, OrderStatusUpdate


def _load_order_with_relations(db: Session, order_id: int) -> Order | None:
    """Carga un pedido junto con sus ítems e historial de estados en una consulta eficiente."""
    stmt = (
        select(Order)
        .options(
            selectinload(Order.items),
            selectinload(Order.status_history),
        )
        .where(Order.id == order_id)
    )
    return db.scalars(stmt).first()


def assert_can_view_order(user: User, order: Order) -> None:
    """Verifica que el usuario tenga permiso sobre este recurso específico (prevención de IDOR)."""
    if user.role == UserRole.ADMIN:
        return
    if user.role == UserRole.OPERATOR:
        if user.store_id != order.store_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado: este pedido pertenece a otra tienda.",
            )
        return
    if user.role == UserRole.CUSTOMER:
        if order.customer_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado: no puedes consultar pedidos de otros clientes.",
            )
        return


def create_order(db: Session, *, customer: User, payload: OrderCreate) -> Order:
    """Crea un pedido nuevo calculando precios y subtotales exclusivamente en el servidor."""
    store = db.get(Store, payload.store_id)
    if store is None or not store.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La tienda seleccionada no existe o no está activa.",
        )

    # Agrupamos cantidades por si el cliente envía el mismo product_id más de una vez
    quantities_by_product: dict[int, int] = {}
    for item in payload.items:
        quantities_by_product[item.product_id] = (
            quantities_by_product.get(item.product_id, 0) + item.quantity
        )

    product_ids = list(quantities_by_product.keys())
    products = list(
        db.scalars(select(Product).where(Product.id.in_(product_ids))).all()
    )
    products_by_id = {p.id: p for p in products}

    if len(products_by_id) != len(product_ids):
        missing = set(product_ids) - set(products_by_id.keys())
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Productos inexistentes: {sorted(missing)}",
        )

    total_amount = Decimal("0.00")
    order_items: list[OrderItem] = []

    for prod_id, qty in quantities_by_product.items():
        product = products_by_id[prod_id]
        if product.store_id != store.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El producto '{product.name}' (ID {product.id}) no pertenece a la tienda {store.name}.",
            )
        if not product.is_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El producto '{product.name}' no está disponible actualmente.",
            )

        unit_price = Decimal(str(product.price)).quantize(Decimal("0.01"))
        subtotal = (unit_price * Decimal(qty)).quantize(Decimal("0.01"))
        total_amount += subtotal

        order_items.append(
            OrderItem(
                product_id=product.id,
                product_name_snapshot=product.name,
                unit_price_snapshot=unit_price,
                quantity=qty,
                subtotal=subtotal,
            )
        )

    order = Order(
        customer_id=customer.id,
        store_id=store.id,
        status=OrderStatus.RECEIVED,
        total_amount=total_amount,
        notes=payload.notes,
        items=order_items,
    )
    db.add(order)
    db.flush()  # Obtenemos order.id antes de confirmar la transacción

    initial_history = OrderStatusHistory(
        order_id=order.id,
        from_status=None,
        to_status=OrderStatus.RECEIVED,
        changed_by_user_id=customer.id,
        comment="Pedido creado por el cliente.",
    )
    db.add(initial_history)
    db.commit()

    loaded = _load_order_with_relations(db, order.id)
    assert loaded is not None
    return loaded


def list_orders_for_user(
    db: Session,
    *,
    user: User,
    store_id: int | None = None,
    status_filter: OrderStatus | None = None,
) -> list[Order]:
    """Lista pedidos aplicando aislamiento estricto según el rol del usuario."""
    stmt = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.status_history),
    )

    if user.role == UserRole.CUSTOMER:
        stmt = stmt.where(Order.customer_id == user.id)
        if store_id is not None:
            stmt = stmt.where(Order.store_id == store_id)
    elif user.role == UserRole.OPERATOR:
        if user.store_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El operador no tiene una tienda asignada.",
            )
        if store_id is not None and store_id != user.store_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes listar pedidos de otra tienda.",
            )
        stmt = stmt.where(Order.store_id == user.store_id)
    elif user.role == UserRole.ADMIN:
        if store_id is not None:
            stmt = stmt.where(Order.store_id == store_id)

    if status_filter is not None:
        stmt = stmt.where(Order.status == status_filter)

    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc())
    return list(db.scalars(stmt).all())


def get_order_for_user(db: Session, *, user: User, order_id: int) -> Order:
    """Obtiene un pedido por ID y valida que el usuario tenga acceso a él."""
    order = _load_order_with_relations(db, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido #{order_id} no encontrado.",
        )
    assert_can_view_order(user, order)
    return order


def update_order_status(
    db: Session,
    *,
    actor: User,
    order_id: int,
    payload: OrderStatusUpdate,
) -> Order:
    """Actualiza el estado de un pedido validando permisos RBAC/anti-IDOR y la máquina de estados."""
    order = _load_order_with_relations(db, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido #{order_id} no encontrado.",
        )

    # 1. Validación de permisos por rol y por recurso (Anti-IDOR)
    if actor.role == UserRole.CUSTOMER:
        if order.customer_id != actor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes modificar pedidos de otros clientes.",
            )
        # Un cliente solo puede cancelar su propio pedido si aún está en estado RECEIVED
        if payload.status != OrderStatus.CANCELLED or order.status != OrderStatus.RECEIVED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Como cliente solo puedes cancelar tu pedido mientras esté en estado RECEIVED.",
            )
    elif actor.role == UserRole.OPERATOR:
        if actor.store_id != order.store_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes cambiar el estado de un pedido que pertenece a otra tienda.",
            )
    elif actor.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Rol no autorizado para cambiar el estado del pedido.",
        )

    # 2. Validación de la Máquina de Estados
    current_status = order.status
    target_status = payload.status

    if current_status == target_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El pedido ya se encuentra en el estado {current_status.value}.",
        )

    allowed_targets = VALID_STATUS_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_targets:
        allowed_names = ", ".join(s.value for s in sorted(allowed_targets, key=lambda x: x.value)) or "ninguno (estado terminal)"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Transición de estado inválida: {current_status.value} -> {target_status.value}. "
                f"Transiciones permitidas desde {current_status.value}: {allowed_names}."
            ),
        )

    now = datetime.now(timezone.utc)
    order.status = target_status
    order.updated_at = now
    if target_status == OrderStatus.READY and order.ready_at is None:
        order.ready_at = now

    history_entry = OrderStatusHistory(
        order_id=order.id,
        from_status=current_status,
        to_status=target_status,
        changed_by_user_id=actor.id,
        comment=payload.comment,
        changed_at=now,
    )
    db.add(history_entry)
    db.commit()

    updated = _load_order_with_relations(db, order.id)
    assert updated is not None
    return updated
