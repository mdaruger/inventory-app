"""Photo-folder catalog ingestion.

Flow
----
1. save_photos()  -> store uploaded images under UPLOAD_DIR/<business_id>/<batch>/
2. extract_batch() -> run the pluggable OCR extractor over each photo, returning
                      editable candidate rows for the review screen.
3. commit_items()  -> write the admin-confirmed rows into the business catalog.

Extraction is deliberately a separate step from committing so a human always
reviews/corrects the OCR output before it hits the catalog.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict
from typing import List

from sqlalchemy.orm import Session

from app.config import UPLOAD_DIR
from app.services import core
from app.services.ocr import ExtractedItem, get_extractor

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def _batch_dir(business_id: int, batch_id: str) -> str:
    return os.path.join(UPLOAD_DIR, str(business_id), batch_id)


def save_photos(business_id: int, files: List) -> tuple[str, List[str]]:
    """Persist uploaded files; returns (batch_id, list of saved relative paths)."""
    batch_id = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
    target = _batch_dir(business_id, batch_id)
    os.makedirs(target, exist_ok=True)

    saved = []
    for f in files:
        filename = os.path.basename(f.filename or "")
        if not filename:
            continue
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXT:
            continue
        # Avoid collisions / unsafe names
        safe = f"{uuid.uuid4().hex[:8]}{ext}"
        dest = os.path.join(target, safe)
        with open(dest, "wb") as out:
            out.write(f.file.read())
        saved.append(os.path.join(str(business_id), batch_id, safe))
    return batch_id, saved


def extract_batch(saved_paths: List[str]) -> List[dict]:
    """Run OCR on each saved photo and return candidate dicts for the review UI."""
    extractor = get_extractor()
    results = []
    for rel in saved_paths:
        abs_path = os.path.join(UPLOAD_DIR, rel)
        items: List[ExtractedItem] = extractor.extract(abs_path)
        for item in items:
            d = asdict(item)
            d["image"] = rel  # relative path, served via /uploads
            results.append(d)
    return results


def commit_items(db: Session, business_id: int, rows: List[dict]) -> int:
    """Create catalog items from confirmed review rows. Returns count created.

    Each row is expected to have: name, price, sku (optional), image (optional).
    Rows without a name are skipped.
    """
    created = 0
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        try:
            price = float(row.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        core.create_catalog_item(
            db,
            business_id=business_id,
            name=name,
            price=price,
            sku=(row.get("sku") or "").strip(),
            source_image=(row.get("image") or "").strip(),
        )
        created += 1
    return created
