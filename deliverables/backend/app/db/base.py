from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. Import every model module in db/models/__init__.py
    so Alembic autogenerate can see them."""
