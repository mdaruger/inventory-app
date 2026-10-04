FROM python:3.11-slim

# System deps: tesseract for offline OCR, plus libs Pillow needs
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract5 \
    libjpeg62-turbo \
    zlib1g \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Persisted data (sqlite db + uploaded photos) lives here; mounted as a volume
RUN mkdir -p /app/data/uploads

ENV DATABASE_URL=sqlite:////app/data/inventory.db \
    UPLOAD_DIR=/app/data/uploads \
    SECRET_KEY=change-me-in-production \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
