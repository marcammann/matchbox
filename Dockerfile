# Stage 1: Build frontend
FROM node:22-slim AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

# Stage 2: Python backend
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
    libffi-dev libcairo2 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml .python-version ./
RUN uv sync --no-dev

COPY matchbox/ matchbox/
COPY templates/ templates/

COPY --from=frontend /web/build web/build/

RUN uv sync --no-dev

ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8000

CMD ["uv", "run", "matchbox-web"]
