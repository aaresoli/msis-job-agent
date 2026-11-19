"""SQLAlchemy declarative base."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for HOPE persistence models."""
