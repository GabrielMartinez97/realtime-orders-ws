"""Modelos ORM para Tiendas (Stores)."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.product import Product
    from app.models.user import User


def utc_now() -> datetime:
    """Retorna la fecha/hora actual en UTC con zona horaria explícita."""
    return datetime.now(timezone.utc)


class Store(Base):
    """Representa una tienda o sucursal de la cadena."""

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relaciones
    operators: Mapped[list["User"]] = relationship("User", back_populates="store")
    products: Mapped[list["Product"]] = relationship(
        "Product", back_populates="store", cascade="all, delete-orphan"
    )
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="store")
