# Dockerfile for FastAPI Backend
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for psycopg2 and tools
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy local dependencies first to install them as packages
COPY services/membrane /app/services/membrane
COPY packages/shared /app/packages/shared

# Install membrane client adapter
RUN pip install --no-cache-dir -e /app/services/membrane

# Copy requirements and install backend dependencies
COPY services/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy backend service code
COPY services/backend /app/services/backend

# Expose port and start FastAPI application
EXPOSE 8002

ENV PYTHONPATH=/app

CMD ["python", "services/backend/main.py"]
