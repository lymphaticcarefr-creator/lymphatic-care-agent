FROM python:3.11-slim

# Install minimal system deps (loguru log rotation, healthcheck curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first to leverage Docker layer cache
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Persistent log directory (mounted as volume in compose)
RUN mkdir -p /app/data

EXPOSE 8000

# Force asyncio loop (Brevo IPv6 fix) — see main.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio"]
