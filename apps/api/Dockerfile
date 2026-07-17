FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/api/requirements.lock apps/api/requirements.lock
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/src apps/api/src

RUN python -m pip install --requirement apps/api/requirements.lock \
    && python -m pip install --no-build-isolation --no-deps --editable apps/api

COPY apps/api/alembic.ini apps/api/alembic.ini
COPY apps/api/migrations apps/api/migrations

RUN useradd --create-home --uid 10001 extent
USER extent

CMD ["sh", "-c", "python -m uvicorn extent_api.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
