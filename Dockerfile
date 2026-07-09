# syntax=docker/dockerfile:1

# --- Stage 1: Build the Next.js frontend (static export) ---
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python backend serving API + static frontend ---
FROM python:3.12-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV FINALLY_DB_PATH=/app/db/finally.db

# Install production dependencies from the lockfile
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy backend source and finish install
COPY backend/ ./
RUN uv sync --frozen --no-dev

# Copy the built frontend into the static dir the backend serves
COPY --from=frontend /frontend/out ./static

EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
