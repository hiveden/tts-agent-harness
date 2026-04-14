#!/bin/sh
set -e

echo "Running database migrations..."
cd /app/server
python -m alembic upgrade head
cd /app

echo "Starting services..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
