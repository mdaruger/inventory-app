"""FastAPI application: routes, middleware, and startup wiring."""
import json
import os

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session

from app import auth, config
from app.database import Base, engine, get_db
from app.models import Business, CatalogItem, Inventory, MovementType, Role, Store, User
from app.seed import seed
from app.services import core, ingestion

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="Inventory Manager")
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Serve uploaded photos (read-only) and static assets.
os.makedirs(config.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=config.UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)
    if config.SEED_ON_STARTUP:
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            seed(db)
        finally:
            db.close()


def render(request: Request, template: str, user: User, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(
        template, {"request": request, "user": user, "Role": Role, **ctx}
    )


# --- auth routes ------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth.authenticate(db, username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password."},
            status_code=401,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --- home: route by role ----------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role == Role.SUPERUSER:
        return RedirectResponse("/admin", status_code=303)
    if user.role == Role.BUSINESS_ADMIN:
        return RedirectResponse("/business", status_code=303)
    return RedirectResponse("/sales", status_code=303)


# --- superuser admin --------------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_home(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.SUPERUSER)),
):
    businesses = core.list_businesses(db)
    users = core.list_users(db)
    return render(request, "admin.html", user, businesses=businesses, users=users)


@app.post("/admin/businesses")
def admin_create_business(
    name: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.SUPERUSER)),
):
    if name.strip():
        core.create_business(db, name)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/stores")
def admin_create_store(
    business_id: int = Form(...),
    name: str = Form(...),
    location: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.SUPERUSER)),
):
    core.create_store(db, business_id, name, location)
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/users/new", response_class=HTMLResponse)
def admin_user_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.SUPERUSER)),
):
    businesses = core.list_businesses(db)
    stores = db.query(Store).order_by(Store.name).all()
    return render(request, "user_form.html", user, businesses=businesses, stores=stores)


@app.post("/admin/users")
def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    business_ids: list[int] = Form(default=[]),
    store_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.SUPERUSER)),
):
    if db.query(User).filter(User.username == username.strip()).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    core.create_user(
        db,
        username=username,
        password=password,
        role=Role(role),
        business_ids=business_ids,
        store_ids=store_ids,
    )
    return RedirectResponse("/admin", status_code=303)


# --- business admin ---------------------------------------------------------------

def _resolve_business(request: Request, db: Session, user: User, business_id: int | None) -> Business:
    """Pick the active business for an admin, enforcing access."""
    biz_ids = auth.accessible_business_ids(db, user)
    if business_id is None:
        if not biz_ids:
            raise HTTPException(status_code=403, detail="No business access")
        business_id = biz_ids[0]
    if not auth.can_access_business(db, user, business_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    return db.query(Business).get(business_id)


@app.get("/business", response_class=HTMLResponse)
def business_home(
    request: Request,
    business_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.BUSINESS_ADMIN, Role.SUPERUSER)),
):
    businesses = core.list_businesses(db, auth.accessible_business_ids(db, user))
    active = _resolve_business(request, db, user, business_id)
    stores = core.list_stores(db, active.id)
    catalog = core.list_catalog(db, active.id)
    return render(
        request,
        "business.html",
        user,
        businesses=businesses,
        active=active,
        stores=stores,
        catalog=catalog,
    )


@app.post("/business/{business_id}/catalog/upload", response_class=HTMLResponse)
async def catalog_upload(
    request: Request,
    business_id: int,
    photos: list[UploadFile] = [],
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.BUSINESS_ADMIN, Role.SUPERUSER)),
):
    if not auth.can_access_business(db, user, business_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    batch_id, saved = ingestion.save_photos(business_id, photos)
    candidates = ingestion.extract_batch(saved)
    active = db.query(Business).get(business_id)
    return render(
        request,
        "review.html",
        user,
        active=active,
        candidates=candidates,
        batch_id=batch_id,
    )


@app.post("/business/{business_id}/catalog/confirm")
async def catalog_confirm(
    request: Request,
    business_id: int,
    rows_json: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.BUSINESS_ADMIN, Role.SUPERUSER)),
):
    if not auth.can_access_business(db, user, business_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        rows = json.loads(rows_json)
    except json.JSONDecodeError:
        rows = []
    ingestion.commit_items(db, business_id, rows)
    return RedirectResponse(f"/business?business_id={business_id}", status_code=303)


@app.post("/business/{business_id}/catalog/manual")
def catalog_manual(
    business_id: int,
    name: str = Form(...),
    price: float = Form(0.0),
    sku: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.BUSINESS_ADMIN, Role.SUPERUSER)),
):
    if not auth.can_access_business(db, user, business_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    if name.strip():
        core.create_catalog_item(db, business_id, name, price, sku=sku)
    return RedirectResponse(f"/business?business_id={business_id}", status_code=303)


@app.get("/business/{business_id}/inventory", response_class=HTMLResponse)
def business_inventory(
    request: Request,
    business_id: int,
    store_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.BUSINESS_ADMIN, Role.SUPERUSER)),
):
    if not auth.can_access_business(db, user, business_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    active = db.query(Business).get(business_id)
    stores = core.list_stores(db, business_id)
    if store_id is None and stores:
        store_id = stores[0].id
    catalog = core.list_catalog(db, business_id)
    inv_map = {}
    if store_id:
        for inv in core.store_inventory(db, store_id):
            inv_map[inv.catalog_item_id] = inv
    return render(
        request,
        "inventory.html",
        user,
        active=active,
        stores=stores,
        store_id=store_id,
        catalog=catalog,
        inv_map=inv_map,
    )


@app.post("/business/{business_id}/inventory")
def business_set_inventory(
    business_id: int,
    store_id: int = Form(...),
    catalog_item_id: int = Form(...),
    quantity: int = Form(...),
    low_stock_threshold: int = Form(5),
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.BUSINESS_ADMIN, Role.SUPERUSER)),
):
    if not auth.can_access_business(db, user, business_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    core.upsert_inventory(db, store_id, catalog_item_id, quantity, low_stock_threshold)
    return RedirectResponse(
        f"/business/{business_id}/inventory?store_id={store_id}", status_code=303
    )


# --- dashboard --------------------------------------------------------------------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    business_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_roles(Role.BUSINESS_ADMIN, Role.SUPERUSER)),
):
    businesses = core.list_businesses(db, auth.accessible_business_ids(db, user))
    active = _resolve_business(request, db, user, business_id)
    data = core.dashboard_data(db, active.id)
    return render(
        request, "dashboard.html", user, businesses=businesses, active=active, data=data
    )


# --- sales portal -----------------------------------------------------------------

@app.get("/sales", response_class=HTMLResponse)
def sales_home(
    request: Request,
    store_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_login),
):
    store_ids = auth.accessible_store_ids(db, user)
    stores = db.query(Store).filter(Store.id.in_(store_ids or [-1])).order_by(Store.name).all()
    if store_id is None and stores:
        store_id = stores[0].id
    if store_id and store_id not in store_ids:
        raise HTTPException(status_code=403, detail="Forbidden")

    rows = []
    if store_id:
        for inv in core.store_inventory(db, store_id):
            rows.append(
                {
                    "inventory_id": inv.id,
                    "name": inv.catalog_item.name,
                    "sku": inv.catalog_item.sku,
                    "price": inv.catalog_item.price,
                    "quantity": inv.quantity,
                    "low": inv.quantity <= inv.low_stock_threshold,
                }
            )
    return render(
        request, "sales.html", user, stores=stores, store_id=store_id, rows=rows
    )


@app.post("/sales/movement")
def sales_movement(
    request: Request,
    inventory_id: int = Form(...),
    store_id: int = Form(...),
    movement_type: str = Form(...),
    quantity: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(auth.require_login),
):
    inv = db.query(Inventory).get(inventory_id)
    if not inv or not auth.can_access_store(db, user, inv.store_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        core.record_movement(db, inv, MovementType(movement_type), quantity, user_id=user.id)
        msg = None
    except ValueError as exc:
        msg = str(exc)
    url = f"/sales?store_id={store_id}"
    if msg:
        # surface the error via a query flag
        url += f"&error={msg}"
    return RedirectResponse(url, status_code=303)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
