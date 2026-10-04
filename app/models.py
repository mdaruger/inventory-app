"""Data models for the multi-tenant inventory system.

Relationships
-------------
Business 1--* Store
Business 1--* CatalogItem
Store    1--* Inventory  *--1 CatalogItem
User     *--* Business   (via UserBusinessAccess)   -> admin/sales scoping
User     *--* Store      (via UserStoreAccess)       -> sales scoping
Inventory 1--* StockMovement                          -> audit of sales/receipts
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Role(str, enum.Enum):
    SUPERUSER = "SUPERUSER"          # full access to all businesses
    BUSINESS_ADMIN = "BUSINESS_ADMIN"  # manage catalog/inventory for assigned businesses
    SALES = "SALES"                  # view/update inventory for assigned stores


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(Role), nullable=False, default=Role.SALES)
    created_at = Column(DateTime, default=datetime.utcnow)

    business_access = relationship(
        "UserBusinessAccess", back_populates="user", cascade="all, delete-orphan"
    )
    store_access = relationship(
        "UserStoreAccess", back_populates="user", cascade="all, delete-orphan"
    )


class Business(Base):
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    stores = relationship("Store", back_populates="business", cascade="all, delete-orphan")
    catalog_items = relationship(
        "CatalogItem", back_populates="business", cascade="all, delete-orphan"
    )


class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    location = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    business = relationship("Business", back_populates="stores")
    inventory = relationship(
        "Inventory", back_populates="store", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_store_business_name"),)


class UserBusinessAccess(Base):
    """Grants a user (admin or sales) access to a business."""
    __tablename__ = "user_business_access"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)

    user = relationship("User", back_populates="business_access")
    business = relationship("Business")

    __table_args__ = (
        UniqueConstraint("user_id", "business_id", name="uq_user_business"),
    )


class UserStoreAccess(Base):
    """Scopes a sales user to specific stores."""
    __tablename__ = "user_store_access"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)

    user = relationship("User", back_populates="store_access")
    store = relationship("Store")

    __table_args__ = (UniqueConstraint("user_id", "store_id", name="uq_user_store"),)


class CatalogItem(Base):
    """A product definition with price, scoped to a business."""
    __tablename__ = "catalog_items"

    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    sku = Column(String, nullable=False)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    source_image = Column(String, nullable=True)  # path of the photo it was extracted from
    created_at = Column(DateTime, default=datetime.utcnow)

    business = relationship("Business", back_populates="catalog_items")
    inventory = relationship(
        "Inventory", back_populates="catalog_item", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("business_id", "sku", name="uq_catalog_business_sku"),)


class Inventory(Base):
    """Per-store stock level for a catalog item."""
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)
    catalog_item_id = Column(
        Integer, ForeignKey("catalog_items.id"), nullable=False, index=True
    )
    quantity = Column(Integer, nullable=False, default=0)
    low_stock_threshold = Column(Integer, nullable=False, default=5)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store", back_populates="inventory")
    catalog_item = relationship("CatalogItem", back_populates="inventory")
    movements = relationship(
        "StockMovement", back_populates="inventory", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("store_id", "catalog_item_id", name="uq_inventory_store_item"),
    )


class MovementType(str, enum.Enum):
    SALE = "SALE"          # stock leaving (sold)
    RECEIPT = "RECEIPT"    # stock arriving (received)
    ADJUSTMENT = "ADJUSTMENT"


class StockMovement(Base):
    """Audit log of every stock change."""
    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False, index=True)
    movement_type = Column(Enum(MovementType), nullable=False)
    quantity_delta = Column(Integer, nullable=False)  # negative for sales
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    inventory = relationship("Inventory", back_populates="movements")
