"""Database seeding: superuser + sample businesses/stores/catalog/inventory."""
from sqlalchemy.orm import Session

from app.config import SEED_SUPERUSER_PASSWORD, SEED_SUPERUSER_USERNAME
from app.models import MovementType, Role, User
from app.services import core


def seed(db: Session) -> None:
    # Superuser (idempotent)
    if not db.query(User).filter(User.username == SEED_SUPERUSER_USERNAME).first():
        core.create_user(
            db,
            username=SEED_SUPERUSER_USERNAME,
            password=SEED_SUPERUSER_PASSWORD,
            role=Role.SUPERUSER,
        )

    # Only seed demo data on an otherwise-empty system.
    if core.list_businesses(db):
        return

    # --- Business 1: Acme Retail, 2 stores ---
    acme = core.create_business(db, "Acme Retail")
    acme_downtown = core.create_store(db, acme.id, "Downtown", "123 Main St")
    acme_airport = core.create_store(db, acme.id, "Airport", "Terminal B")

    acme_items = [
        ("Widget", 9.99, "WIDGET"),
        ("Gadget", 19.95, "GADGET"),
        ("Gizmo", 4.50, "GIZMO"),
        ("Doohickey", 2.25, "DOOHICKEY"),
    ]
    acme_catalog = [
        core.create_catalog_item(db, acme.id, n, p, sku=s) for n, p, s in acme_items
    ]
    # Inventory: downtown well-stocked, airport low on some items
    core.upsert_inventory(db, acme_downtown.id, acme_catalog[0].id, 50, 10)
    core.upsert_inventory(db, acme_downtown.id, acme_catalog[1].id, 30, 5)
    core.upsert_inventory(db, acme_downtown.id, acme_catalog[2].id, 100, 20)
    core.upsert_inventory(db, acme_airport.id, acme_catalog[0].id, 3, 10)   # low
    core.upsert_inventory(db, acme_airport.id, acme_catalog[1].id, 2, 5)    # low
    core.upsert_inventory(db, acme_airport.id, acme_catalog[3].id, 0, 5)    # out

    # --- Business 2: Globex Foods, 1 store ---
    globex = core.create_business(db, "Globex Foods")
    globex_main = core.create_store(db, globex.id, "Market Square", "9 Market Sq")
    globex_items = [
        ("Coffee Beans 1kg", 24.00, "COFFEE1KG"),
        ("Green Tea Box", 6.75, "GREENTEA"),
        ("Olive Oil 500ml", 12.40, "OLIVE500"),
    ]
    globex_catalog = [
        core.create_catalog_item(db, globex.id, n, p, sku=s) for n, p, s in globex_items
    ]
    core.upsert_inventory(db, globex_main.id, globex_catalog[0].id, 40, 8)
    core.upsert_inventory(db, globex_main.id, globex_catalog[1].id, 5, 8)   # low
    core.upsert_inventory(db, globex_main.id, globex_catalog[2].id, 60, 10)

    # --- A business admin and a sales user ---
    core.create_user(
        db,
        username="acme_admin",
        password="acme123",
        role=Role.BUSINESS_ADMIN,
        business_ids=[acme.id],
    )
    core.create_user(
        db,
        username="acme_sales",
        password="sales123",
        role=Role.SALES,
        business_ids=[acme.id],
        store_ids=[acme_downtown.id],  # only Downtown
    )
