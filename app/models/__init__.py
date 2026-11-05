"""Exportación centralizada de todos los modelos ORM para que SQLAlchemy registre las tablas."""

from app.models.notification import Notification
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

__all__ = [
    "Store",
    "User",
    "UserRole",
    "Product",
    "Order",
    "OrderItem",
    "OrderStatus",
    "OrderStatusHistory",
    "VALID_STATUS_TRANSITIONS",
    "Notification",
]
