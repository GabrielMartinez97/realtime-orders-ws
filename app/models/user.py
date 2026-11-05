"""Modelos ORM para Usuarios y Roles (RBAC)."""

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.notification import Notification
    from app.models.order import Order
    from app.models.store import Store


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    """Roles del sistema con permisos validados en el backend."""

    CUSTOMER = "CUSTOMER"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"


class User(Base):
    """Usuario del sistema (Cliente, Operador de Tienda o Administrador)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, index=True)
    store_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relaciones
    store: Mapped[Optional["Store"]] = relationship("Store", back_populates="operators")
    orders: Mapped[list["Order"]] = relationship(
        "Order", back_populates="customer", foreign_keys="Order.customer_id"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )
