FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt pyproject.toml VERSION ./
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -e .

# Backend source
COPY daiflow/ ./daiflow/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Frontend build output
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8000

# Run migrations then start server
CMD ["sh", "-c", "alembic upgrade head && daiflow start --host 0.0.0.0 --port 8000 --no-browser"]
