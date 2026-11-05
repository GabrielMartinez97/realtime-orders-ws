"""Configuración de SQLAlchemy 2.0 compatible con SQLite y PostgreSQL."""

from collections.abc import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def _build_engine() -> Engine:
    """Construye el motor SQLAlchemy adaptando argumentos según el motor (SQLite vs PostgreSQL)."""
    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}

    engine_instance = create_engine(
        settings.DATABASE_URL,
        connect_args=connect_args,
        pool_pre_ping=not is_sqlite,
    )

    if is_sqlite:
        # En SQLite las llaves foráneas (FOREIGN KEY) vienen desactivadas por defecto.
        # Las activamos en cada conexión para garantizar integridad referencial real.
        @event.listens_for(engine_instance, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine_instance


engine = _build_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Clase base declarativa para todos los modelos ORM."""


def get_db() -> Generator[Session, None, None]:
    """Dependencia FastAPI que provee una sesión de base de datos por petición y la cierra al finalizar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
