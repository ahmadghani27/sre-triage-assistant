#!/bin/sh
set -e

DATA_DIR=/app/data

# Pastikan seed file tersedia di volume (volume kosong akan shadow isi image)
if [ ! -f "$DATA_DIR/seed_runbooks.json" ]; then
    cp /app/seed-data/seed_runbooks.json "$DATA_DIR/"
fi
if [ ! -f "$DATA_DIR/schema.sql" ]; then
    cp /app/seed-data/schema.sql "$DATA_DIR/"
fi

# Inisialisasi database (idempoten, aman dijalankan ulang)
python scripts/seed.py

# Jalankan production WSGI server
exec gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 8 \
    --access-logfile - --error-logfile - \
    "app:create_app()"
