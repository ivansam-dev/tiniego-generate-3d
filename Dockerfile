# Use a lightweight Python base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=on \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PORT=8080

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy dependency files first
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install -r requirements.txt

# Copy application code
COPY . /app

# Create a non-root user (recommended for Cloud Run)
RUN useradd -m appuser
USER appuser

# Expose the port Cloud Run will send traffic to
EXPOSE 8080

# Start the server with uvicorn. Cloud Run provides $PORT.
CMD exec uvicorn api:app --host 0.0.0.0 --port ${PORT} --forwarded-allow-ips=*
