# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Install system dependencies for video/audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libmagic1 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory inside the application folder
WORKDIR /app

# Install Python dependencies first (leverages Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the Uvicorn port
EXPOSE 8000

# Default command runs the web server and Celery worker in the same container
CMD ["sh", "start.sh"]