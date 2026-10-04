# Inventory Manager

A self-contained, multi-tenant inventory management app. Runs as a **single Docker
container** so you can test it on your local machine with one command.

- Multiple **businesses**, each with one or more **stores**
- Role-based access: **Superuser**, **Business Admin**, **Sales**
- Catalog ingestion by **uploading a folder of product/price-tag photos** — the app
  runs offline **OCR (Tesseract)**, then shows a **review screen** so you can edit the
  extracted name / price / SKU before anything is added
- Per-store **inventory** with low-stock thresholds
- Per-business **dashboard**: overall stock, in-stock per store, low/out-of-stock per store
- **Sales portal** scoped to the stores a sales person can access, with sell / receive
  actions that update inventory

Stack: FastAPI + SQLite + Jinja2 (server-rendered HTML). No external services, no API
keys, no network calls — everything runs in the container.

## Quick start (Docker)

```bash
cd inventory-app
docker compose up --build
```

Then open http://localhost:8000 and sign in.

The SQLite database and uploaded photos are stored in `./data` (mounted as a volume),
so they persist across restarts. Delete `./data/inventory.db` to reset.

### Demo logins (seeded on first run)

| Username     | Password  | Role           | Scope                                  |
|--------------|-----------|----------------|----------------------------------------|
| `admin`      | `admin123`| Superuser      | All businesses                         |
| `acme_admin` | `acme123` | Business Admin | Acme Retail                            |
| `acme_sales` | `sales123`| Sales          | Acme Retail → Downtown store only      |

Seeded demo data: **Acme Retail** (Downtown + Airport stores, 4 items, some low/out of
stock) and **Globex Foods** (1 store, 3 items).

## How each role maps to the requirements

- **Superuser** (`/admin`): create businesses & stores, create users, assign a user's
  role and which business(es) they can access. Can also open any business's catalog and
  dashboard.
- **Business Admin** (`/business`): upload catalog photos → review/confirm, add items
  manually, manage per-store inventory, view the dashboard. Limited to assigned
  businesses.
- **Sales** (`/sales`): see inventory only for granted stores; record sales (decrements
  stock) and receipts (increments stock).

## Catalog upload from photos

1. As a business admin, go to **Catalog** and choose a folder of photos (or individual
   image files). Clear printed price tags / shelf labels work best.
2. The app saves the images, runs OCR on each, and parses a candidate **name / price /
   SKU**. Rows it isn't confident about are flagged `low`.
3. You **review and edit** every row, uncheck any you don't want, and confirm.
4. Confirmed rows become catalog items (SKU auto-generated if you leave it blank). The
   source photo is kept and shown next to the item.

The extractor is pluggable (`app/services/ocr.py`). The default is offline Tesseract;
you can set `OCR_BACKEND=noop` to disable OCR (review rows come up blank for manual
entry), or add a new backend without changing the ingestion flow.

## Configuration (environment variables)

| Variable                  | Default                              | Purpose                                   |
|---------------------------|--------------------------------------|-------------------------------------------|
| `DATABASE_URL`            | `sqlite:////app/data/inventory.db`   | SQLAlchemy DB URL                         |
| `UPLOAD_DIR`              | `/app/data/uploads`                  | Where uploaded photos are stored          |
| `SECRET_KEY`              | `local-dev-secret-change-me`         | Session cookie signing key                |
| `OCR_BACKEND`             | `tesseract`                          | `tesseract` or `noop`                     |
| `SEED_ON_STARTUP`         | `true`                               | Seed superuser + demo data on first boot  |
| `SEED_SUPERUSER_USERNAME` | `admin`                              | Seed superuser username                   |
| `SEED_SUPERUSER_PASSWORD` | `admin123`                           | Seed superuser password                   |

Change `SECRET_KEY` and the superuser password for anything beyond local testing.

## Project layout

```
inventory-app/
├── Dockerfile              # python:3.11-slim + tesseract-ocr
├── docker-compose.yml      # single service, port 8000, ./data volume
├── requirements.txt
└── app/
    ├── main.py             # FastAPI app, routes, startup wiring
    ├── config.py           # env-driven configuration
    ├── database.py         # SQLAlchemy engine/session
    ├── models.py           # Business, Store, User, access maps, Catalog, Inventory, Movements
    ├── auth.py             # password hashing, sessions, role & scope checks
    ├── seed.py             # superuser + demo data
    ├── services/
    │   ├── core.py         # businesses/stores/users/catalog/inventory/dashboard
    │   ├── ocr.py          # pluggable extractor (Tesseract / noop)
    │   └── ingestion.py    # save photos → extract → confirm → catalog
    ├── templates/          # Jinja2 pages
    └── static/style.css
```

## Data model

```
Business 1─* Store
Business 1─* CatalogItem
Store    1─* Inventory *─1 CatalogItem
Inventory 1─* StockMovement        (audit log of sales/receipts)
User *─* Business  (UserBusinessAccess)   admin/sales → business scoping
User *─* Store     (UserStoreAccess)      sales      → store scoping
```

## Notes & limitations

- OCR accuracy depends on photo quality; the mandatory review step is where you correct
  it. The parser assumes printed price-tag/label style text (largest `$` number = price,
  longest non-price line = name).
- SQLite is used for zero-setup local testing. For multi-user production you'd point
  `DATABASE_URL` at Postgres and run multiple workers.
- Sessions are signed cookies; set a strong `SECRET_KEY` outside local use.

## Running without Docker (optional)

```bash
pip install -r requirements.txt
# Tesseract must be installed on the host for real OCR, else set OCR_BACKEND=noop
OCR_BACKEND=noop uvicorn app.main:app --reload
```
