"""Pluggable catalog extraction from product photos.

The extractor turns an image into a list of candidate catalog items
(name / price / sku + a confidence flag). The default backend uses Tesseract
OCR entirely offline. The interface is intentionally small so a cloud/vision
backend could be swapped in later without touching the ingestion flow.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Protocol

from app.config import OCR_BACKEND

# Matches prices like $12, $12.50, 12.99, 1,299.00
PRICE_RE = re.compile(r"(?<![\w.])\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")
# Lines that look like a SKU / item code (letters+digits, or long digit runs)
SKU_RE = re.compile(r"\b([A-Z]{2,}[-]?\d{2,}[A-Z0-9-]*|\d{6,})\b")


@dataclass
class ExtractedItem:
    name: str = ""
    price: float = 0.0
    sku: str = ""
    confidence: str = "low"  # "high" | "low" — drives review highlighting
    raw_text: str = ""
    extra: dict = field(default_factory=dict)


class Extractor(Protocol):
    def extract(self, image_path: str) -> List[ExtractedItem]:
        ...


def _parse_text_to_item(text: str) -> ExtractedItem:
    """Heuristic parse of OCR text from a single price-tag / label photo.

    Strategy (printed-label assumption):
      - price = the largest $-prefixed number, else the largest standalone number
      - sku   = first token matching a SKU-ish pattern
      - name  = the longest text line that is not the price/sku
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    item = ExtractedItem(raw_text=text)

    # --- price ---
    dollar_prices = []
    plain_prices = []
    for ln in lines:
        for m in PRICE_RE.finditer(ln):
            val = float(m.group(1).replace(",", ""))
            if "$" in ln[max(0, m.start() - 1): m.end()]:
                dollar_prices.append(val)
            else:
                plain_prices.append(val)
    chosen = dollar_prices or plain_prices
    if chosen:
        item.price = max(chosen)

    # --- sku ---
    for ln in lines:
        m = SKU_RE.search(ln.upper())
        if m:
            item.sku = m.group(1)
            break

    # --- name: longest line that isn't basically just the price/sku ---
    def is_pricey(ln: str) -> bool:
        stripped = ln.replace("$", "").replace(",", "").replace(".", "").strip()
        return stripped.isdigit()

    name_candidates = [
        ln for ln in lines
        if not is_pricey(ln) and (not item.sku or item.sku.lower() not in ln.lower())
    ]
    if name_candidates:
        item.name = max(name_candidates, key=len)

    # confidence: high only if we got both a name and a price
    item.confidence = "high" if (item.name and item.price > 0) else "low"
    return item


class TesseractExtractor:
    """Offline OCR via pytesseract. One image -> one candidate item."""

    def extract(self, image_path: str) -> List[ExtractedItem]:
        try:
            import pytesseract
            from PIL import Image
        except Exception as exc:  # pragma: no cover - dependency/runtime issue
            return [ExtractedItem(confidence="low", extra={"error": f"ocr_unavailable: {exc}"})]

        try:
            with Image.open(image_path) as img:
                img = img.convert("L")  # grayscale helps OCR
                text = pytesseract.image_to_string(img)
        except Exception as exc:
            return [ExtractedItem(confidence="low", extra={"error": f"ocr_failed: {exc}"})]

        item = _parse_text_to_item(text)
        return [item]


class NoopExtractor:
    """Fallback when tesseract isn't present: returns an empty, editable row."""

    def extract(self, image_path: str) -> List[ExtractedItem]:
        return [ExtractedItem(confidence="low", extra={"note": "ocr_disabled"})]


def get_extractor() -> Extractor:
    if OCR_BACKEND == "noop":
        return NoopExtractor()
    return TesseractExtractor()
