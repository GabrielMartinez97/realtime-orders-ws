"""Esquemas Pydantic v2 para el Dashboard Analítico en Tiempo Real (Fase 6)."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StoreSalesItem(BaseModel):
    """Métricas agregadas por sucursal individual."""

    store_id: int
    store_name: str
    active_orders_count: int
    total_orders_count: int
    today_sales_total: Decimal


class DashboardMetrics(BaseModel):
    """Instantánea completa de KPIs y series para gráficos del Dashboard en vivo."""

    scope: str = Field(description="'global' para Admin sin filtro, o 'store' para tienda específica")
    store_id: Optional[int] = None
    store_name: Optional[str] = None
    active_orders_count: int
    total_orders_count: int
    today_sales_total: Decimal
    avg_prep_time_minutes: float
    orders_by_status: dict[str, int]
    sales_by_store: list[StoreSalesItem]
    generated_at: datetime = Field(default_factory=utc_now)
