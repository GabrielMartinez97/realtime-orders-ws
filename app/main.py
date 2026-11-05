"""Punto de entrada principal de la aplicación FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401 - Registra todos los modelos en Base.metadata
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.seed import seed_initial_data
from app.routers import auth, orders, products, stores, users


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Inicializa el esquema de base de datos y carga datos semilla de demostración."""
    Base.metadata.create_all(bind=engine)
    if settings.SEED_DEMO_DATA:
        with SessionLocal() as db:
            seed_initial_data(db)
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description=(
        "Sistema de pedidos multi-tienda en tiempo real con FastAPI, SQLAlchemy, "
        "autenticación JWT, control de acceso por roles (RBAC/anti-IDOR) y WebSockets."
    ),
    lifespan=lifespan,
)

# Configuración estricta de CORS basada en variables de entorno
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next) -> Response:
    """Inyecta cabeceras de seguridad HTTP estándar en todas las respuestas."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


# Registro de Routers REST (Fase 1)
app.include_router(auth.router)
app.include_router(stores.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(orders.router)


@app.get("/api/health", tags=["Sistema"])
def health_check() -> dict[str, str]:
    """Endpoint de verificación de estado del servidor."""
    return {"status": "ok", "phase": "1-rest-auth-rbac"}
