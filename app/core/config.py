"""Configuración centralizada y validada desde variables de entorno (.env)."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Esquema de configuración de la aplicación cargado desde .env."""

    PROJECT_NAME: str = "Sistema de Pedidos en Tiempo Real"
    ENVIRONMENT: str = "development"

    # Base de datos (SQLite por defecto, listo para PostgreSQL)
    DATABASE_URL: str = "sqlite:///./realtime_orders.db"

    # Seguridad JWT
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production-immediately-64-chars-min"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    # Orígenes permitidos (CORS y WebSocket Origin check)
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"

    # Rate Limiting (peticiones por minuto)
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 5
    RATE_LIMIT_ORDERS_PER_MINUTE: int = 10

    # Datos de demostración iniciales
    SEED_DEMO_DATA: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins_list(self) -> list[str]:
        """Convierte la cadena separada por comas en una lista limpia de orígenes."""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de la configuración."""
    return Settings()


settings = get_settings()
