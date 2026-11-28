FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_APP=app:create_app()

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cadangkan seed file agar tersedia walaupun /app/data di-shadow oleh volume
COPY data/schema.sql data/seed_runbooks.json ./seed-data/

COPY app ./app
COPY scripts ./scripts
COPY data/schema.sql data/seed_runbooks.json ./data/
COPY entrypoint.sh ./entrypoint.sh

RUN useradd --create-home --shell /bin/sh sreuser && \
    chown -R sreuser:sreuser /app && \
    chmod +x ./entrypoint.sh

USER sreuser

EXPOSE 5000

ENTRYPOINT ["/app/entrypoint.sh"]
