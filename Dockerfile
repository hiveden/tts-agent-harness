# ============================================================
# TTS Agent Harness — Single container
# Caddy (8080) → FastAPI (8100) + Next.js (3010)
# ============================================================

# Stage 1: build Next.js
FROM node:20-slim AS web-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/ ./
ENV NEXT_PUBLIC_API_URL=
RUN npm run build

# Stage 2: runtime
FROM python:3.11-slim

# Node 20 runtime (must match Stage 1 build version)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl supervisor ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Caddy static binary (let BuildKit inject TARGETARCH automatically)
ARG TARGETARCH
RUN curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=${TARGETARCH}" -o /usr/bin/caddy \
    && chmod +x /usr/bin/caddy

WORKDIR /app

# Copy Next.js standalone build from stage 1
COPY --from=web-build /app/web/.next/standalone ./web/.next/standalone
COPY --from=web-build /app/web/.next/static ./web/.next/standalone/.next/static
COPY --from=web-build /app/web/public ./web/.next/standalone/public

# Python deps
COPY server/pyproject.toml ./server/
RUN pip install --no-cache-dir ./server
COPY server/ ./server/

# Deploy configs
COPY deploy/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh

HEALTHCHECK CMD curl -f http://localhost:8080/healthz || exit 1

EXPOSE 8080

CMD ["/app/start.sh"]
