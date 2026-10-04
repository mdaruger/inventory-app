"""Application configuration, read from environment with sensible local defaults."""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/inventory.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./data/uploads")
SECRET_KEY = os.getenv("SECRET_KEY", "local-dev-secret-change-me")

# OCR extractor backend: "tesseract" (offline, default) or "noop" (for environments
# without tesseract installed; returns empty candidates so the UI still works).
OCR_BACKEND = os.getenv("OCR_BACKEND", "tesseract")

# Seed the database with a superuser + demo data on first startup.
SEED_ON_STARTUP = os.getenv("SEED_ON_STARTUP", "true").lower() == "true"
SEED_SUPERUSER_USERNAME = os.getenv("SEED_SUPERUSER_USERNAME", "admin")
SEED_SUPERUSER_PASSWORD = os.getenv("SEED_SUPERUSER_PASSWORD", "admin123")

os.makedirs(UPLOAD_DIR, exist_ok=True)
