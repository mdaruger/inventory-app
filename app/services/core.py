"""Core domain services: businesses, stores, users, catalog, inventory, dashboard."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import accessible_store_ids, hash_password
from app.models import (
    Business,
    CatalogItem,
    Inventory,
    MovementType,
    Role,
    StockMovement,
    Store,
    User,
    UserBusinessAccess,
    UserStoreAccess,
)


# --- businesses & stores ----------------------------------------------------------

def create_business(db: Session, name: str) -> Business:
    biz = Business(name=name.strip())
    db.add(biz)
    db.commit()
    db.refresh(biz)
    return biz


def list_businesses(db: Session, ids: Optional[List[int]] = None) -> List[Business]:
    q = db.query(Business)
    if ids is not None:
        q = q.filter(Business.id.in_(ids or [-1]))
    return q.order_by(Business.name).all()


def create_store(db: Session, business_id: int, name: str, location: str = "") -> Store:
    store = Store(business_id=business_id, name=name.strip(), location=location.strip())
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def list_stores(db: Session, business_id: int) -> List[Store]:
    return (
        db.query(Store)
        .filter(Store.business_id == business_id)
        .order_by(Store.name)
        .all()
    )


# --- users ------------------------------------------------------------------------

def create_user(
    db: Session,
    username: str,
    password: str,
    role: Role,
    business_ids: Optional[List[int]] = None,
    store_ids: Optional[List[int]] = None,
) -> User:
    user = User(
        username=username.strip(),
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.flush()  # get user.id

    for bid in business_ids or []:
        db.add(UserBusinessAccess(user_id=user.id, business_id=bid))
    for sid in store_ids or []:
        db.add(UserStoreAccess(user_id=user.id, store_id=sid))

    db.commit()
    db.refresh(user)
    return user


def set_user_access(
    db: Session,
    user: User,
    business_ids: List[int],
    store_ids: List[int],
) -> None:
    """Replace a user's business and store access grants."""
    db.query(UserBusinessAccess).filter(UserBusinessAccess.user_id == user.id).delete()
    db.query(UserStoreAccess).filter(UserStoreAccess.user_id == user.id).delete()
    for bid in business_ids:
        db.add(UserBusinessAccess(user_id=user.id, business_id=bid))
    for sid in store_ids:
        db.add(UserStoreAccess(user_id=user.id, store_id=sid))
    db.commit()


def list_users(db: Session) -> List[User]:
    return db.query(User).order_by(User.username).all()


# --- catalog ----------------------------------------------------------------------

def _unique_sku(db: Session, business_id: int, base: str) -> str:
    """Ensure the SKU is unique within the business, suffixing if needed."""
    base = (base or "SKU").strip() or "SKU"
    sku = base
    i = 1
    while (
        db.query(CatalogItem)
        .filter(CatalogItem.business_id == business_id, CatalogItem.sku == sku)
        .first()
    ):
        i += 1
        sku = f"{base}-{i}"
    return sku


def create_catalog_item(
    db: Session,
    business_id: int,
    name: str,
    price: float,
    sku: str = "",
    source_image: str = "",
) -> CatalogItem:
    sku = _unique_sku(db, business_id, sku or _slug(name))
    item = CatalogItem(
        business_id=business_id,
        sku=sku,
        name=name.strip(),
        price=float(price or 0),
        source_image=source_image or None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _slug(name: str) -> str:
    base = "".join(c for c in (name or "").upper() if c.isalnum())[:8]
    return base or "ITEM"


def list_catalog(db: Session, business_id: int) -> List[CatalogItem]:
    return (
        db.query(CatalogItem)
        .filter(CatalogItem.business_id == business_id)
        .order_by(CatalogItem.name)
        .all()
    )


# --- inventory --------------------------------------------------------------------

def upsert_inventory(
    db: Session,
    store_id: int,
    catalog_item_id: int,
    quantity: int,
    low_stock_threshold: Optional[int] = None,
) -> Inventory:
    inv = (
        db.query(Inventory)
        .filter(
            Inventory.store_id == store_id,
            Inventory.catalog_item_id == catalog_item_id,
        )
        .first()
    )
    if inv is None:
        inv = Inventory(
            store_id=store_id,
            catalog_item_id=catalog_item_id,
            quantity=max(0, int(quantity)),
            low_stock_threshold=low_stock_threshold if low_stock_threshold is not None else 5,
        )
        db.add(inv)
    else:
        inv.quantity = max(0, int(quantity))
        if low_stock_threshold is not None:
            inv.low_stock_threshold = int(low_stock_threshold)
    db.commit()
    db.refresh(inv)
    return inv


def record_movement(
    db: Session,
    inventory: Inventory,
    movement_type: MovementType,
    quantity: int,
    user_id: Optional[int] = None,
) -> Inventory:
    """Apply a stock movement. SALE decrements, RECEIPT increments."""
    qty = abs(int(quantity))
    delta = -qty if movement_type == MovementType.SALE else qty
    new_qty = inventory.quantity + delta
    if new_qty < 0:
        raise ValueError("Insufficient stock for this sale.")
    inventory.quantity = new_qty
    db.add(
        StockMovement(
            inventory_id=inventory.id,
            movement_type=movement_type,
            quantity_delta=delta,
            user_id=user_id,
        )
    )
    db.commit()
    db.refresh(inventory)
    return inventory


def store_inventory(db: Session, store_id: int) -> List[Inventory]:
    return (
        db.query(Inventory)
        .filter(Inventory.store_id == store_id)
        .join(CatalogItem)
        .order_by(CatalogItem.name)
        .all()
    )


# --- dashboard --------------------------------------------------------------------

def dashboard_data(db: Session, business_id: int) -> dict:
    """Aggregate dashboard metrics for a business (req 5a/5b/5c)."""
    stores = list_stores(db, business_id)
    store_ids = [s.id for s in stores]

    total_units = (
        db.query(func.coalesce(func.sum(Inventory.quantity), 0))
        .filter(Inventory.store_id.in_(store_ids or [-1]))
        .scalar()
    )
    distinct_items = (
        db.query(func.count(func.distinct(Inventory.catalog_item_id)))
        .filter(Inventory.store_id.in_(store_ids or [-1]))
        .scalar()
    )

    per_store = []
    for store in stores:
        rows = (
            db.query(Inventory, CatalogItem)
            .join(CatalogItem, Inventory.catalog_item_id == CatalogItem.id)
            .filter(Inventory.store_id == store.id)
            .order_by(CatalogItem.name)
            .all()
        )
        in_stock = [
            {"name": ci.name, "sku": ci.sku, "quantity": inv.quantity}
            for inv, ci in rows
            if inv.quantity > 0
        ]
        low_stock = [
            {
                "name": ci.name,
                "sku": ci.sku,
                "quantity": inv.quantity,
                "threshold": inv.low_stock_threshold,
            }
            for inv, ci in rows
            if inv.quantity <= inv.low_stock_threshold
        ]
        per_store.append(
            {
                "store": store,
                "in_stock": in_stock,
                "low_stock": low_stock,
                "total_units": sum(inv.quantity for inv, _ in rows),
            }
        )

    return {
        "total_units": total_units or 0,
        "distinct_items": distinct_items or 0,
        "store_count": len(stores),
        "per_store": per_store,
    }
