# ============================================================
# TTS Agent Harness — Single-stage Dockerfile (lighter build)
# Runs FastAPI (8100) + Next.js (3010) in one container
# ============================================================

FROM node:20-slim

# System deps + Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ffmpeg curl supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Next.js build ---
COPY web/package.json web/package-lock.json ./web/
RUN cd web && npm ci --ignore-scripts
COPY web/ ./web/
ENV NEXT_PUBLIC_API_URL=http://localhost:8100
RUN cd web && npm run build

# --- Python deps ---
COPY server/pyproject.toml ./server/
RUN python3 -m venv /app/.venv && \
    /app/.venv/bin/pip install --no-cache-dir ./server 2>/dev/null || \
    /app/.venv/bin/pip install --no-cache-dir -e ./server
COPY server/ ./server/

# Supervisor config
COPY deploy/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 3010 8100

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
