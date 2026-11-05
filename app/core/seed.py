"""Datos semilla (Seed) para desarrollo y demostración del proyecto."""

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.product import Product
from app.models.store import Store
from app.models.user import User, UserRole


def seed_initial_data(db: Session) -> None:
    """Crea tiendas, usuarios por cada rol y catálogo inicial si la base de datos está vacía."""
    existing_store = db.scalars(select(Store).limit(1)).first()
    if existing_store is not None:
        return

    # 1. Crear Tiendas
    store_centro = Store(
        name="Sucursal Centro",
        address="Av. Libertador 1250, Local 4",
        is_active=True,
    )
    store_norte = Store(
        name="Sucursal Norte",
        address="Boulevard del Parque 480",
        is_active=True,
    )
    db.add_all([store_centro, store_norte])
    db.flush()

    # 2. Crear Usuarios (1 Admin, 2 Operadores por tienda, 2 Clientes)
    users = [
        User(
            email="admin@tiendas.com",
            full_name="Administrador General",
            password_hash=hash_password("Admin123!"),
            role=UserRole.ADMIN,
            store_id=None,
            is_active=True,
        ),
        User(
            email="operador.centro@tiendas.com",
            full_name="Operador Sucursal Centro",
            password_hash=hash_password("Operador123!"),
            role=UserRole.OPERATOR,
            store_id=store_centro.id,
            is_active=True,
        ),
        User(
            email="operador.norte@tiendas.com",
            full_name="Operador Sucursal Norte",
            password_hash=hash_password("Operador123!"),
            role=UserRole.OPERATOR,
            store_id=store_norte.id,
            is_active=True,
        ),
        User(
            email="ana@cliente.com",
            full_name="Ana Gómez (Cliente)",
            password_hash=hash_password("Cliente123!"),
            role=UserRole.CUSTOMER,
            store_id=None,
            is_active=True,
        ),
        User(
            email="carlos@cliente.com",
            full_name="Carlos Ruiz (Cliente)",
            password_hash=hash_password("Cliente123!"),
            role=UserRole.CUSTOMER,
            store_id=None,
            is_active=True,
        ),
    ]
    db.add_all(users)

    # 3. Crear Catálogo de Productos por Tienda
    products = [
        # Sucursal Centro
        Product(
            store_id=store_centro.id,
            name="Hamburguesa Doble Smash",
            description="Doble medallón de carne 120g, cheddar, cebolla crispy y salsa de la casa.",
            price=Decimal("12.50"),
            is_available=True,
        ),
        Product(
            store_id=store_centro.id,
            name="Papas Fritas Rústicas",
            description="Porción grande con romero y sal marina.",
            price=Decimal("4.75"),
            is_available=True,
        ),
        Product(
            store_id=store_centro.id,
            name="Limonada de Menta y Jengibre",
            description="Vaso de 500ml recién exprimida.",
            price=Decimal("3.50"),
            is_available=True,
        ),
        # Sucursal Norte
        Product(
            store_id=store_norte.id,
            name="Pizza Napolitana Artesanal",
            description="Masa de fermentación lenta 48h, mozzarella fior di latte y albahaca.",
            price=Decimal("14.90"),
            is_available=True,
        ),
        Product(
            store_id=store_norte.id,
            name="Empanada de Carne Cortada a Cuchillo",
            description="Horneada al barro con especias tradicionales.",
            price=Decimal("2.80"),
            is_available=True,
        ),
        Product(
            store_id=store_norte.id,
            name="Agua Mineral Sin Gas 500ml",
            description="Botella individual fría.",
            price=Decimal("2.10"),
            is_available=True,
        ),
    ]
    db.add_all(products)
    db.commit()
