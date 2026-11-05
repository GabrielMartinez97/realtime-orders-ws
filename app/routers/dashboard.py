"""Router de Dashboard en Vivo (Fase 6): KPIs y series para gráficos de Operador y Admin."""

from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.dashboard import DashboardMetrics
from app.services import dashboard_service

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("", response_model=DashboardMetrics)
def get_live_dashboard_metrics(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    store_id: Annotated[int | None, Query(gt=0)] = None,
) -> DashboardMetrics:
    """Devuelve las métricas en vivo (pedidos activos, ventas del día, prep time y pedidos por estado)."""
    return dashboard_service.get_dashboard_for_user(
        db,
        user=current_user,
        requested_store_id=store_id,
    )
