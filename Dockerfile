# ============================================================
# LocalAI TV - Dockerfile
# Multi-stage build for production
# ============================================================

# Stage 1: Builder - Install dependencies
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Production - Minimal image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies including FFmpeg
RUN apt-get update && apt-get install -y \
    libpq5 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY --chown=app:app . .

# Create required directories
RUN mkdir -p /app/inputs/{images,videos,audios} \
             /app/outputs/{scripts,headlines,audios,reporters,item_video_cache,s3_inject_cache} \
             /app/assets/ads \
             /app/inputs \
             /app/outputs

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; r=requests.get('http://localhost:8000/health', timeout=5); exit(0 if r.status_code==200 else 1)"

# Run the application
CMD ["python", "webhook_server.py"]