# Production Multi-Stage Dockerfile for Telegram Educational Question OCR Bot
FROM python:3.13-slim AS base

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies: Tesseract OCR (with Arabic & English), OpenCV runtime libs, and Arabic fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ara \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    fonts-noto-core \
    fonts-arabeyes \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python package dependencies
COPY pyproject.toml .
RUN pip install --upgrade pip && \
    pip install .

# Copy application source code, migrations, and assets
COPY app/ ./app/
COPY assets/ ./assets/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY scripts/ ./scripts/

# Create non-root user and setup directories
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/storage/originals /app/storage/processed /app/storage/exports /app/storage/tmp && \
    chown -R appuser:appuser /app

USER appuser

# Healthcheck to verify process liveliness
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import socket; socket.socket().close()" || exit 1

CMD ["python", "-m", "app.main"]
