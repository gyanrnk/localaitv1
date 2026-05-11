#!/bin/bash
# ============================================================
# LocalAI TV - VPS Setup Script
# Run this on your Hostinger VPS to set up the environment
# ============================================================

set -e

echo "============================================"
echo "LocalAI TV - VPS Setup"
echo "============================================"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

# Update and install dependencies
echo "[1/7] Installing dependencies..."
apt-get update
apt-get install -y \
    docker.io \
    docker-compose \
    ffmpeg \
    git \
    curl \
    wget

# Check Docker
echo "[2/7] Checking Docker..."
docker --version
docker-compose --version

# Install Docker Compose v2 if needed
if ! docker compose version &>/dev/null; then
    echo "Installing Docker Compose v2..."
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -SL https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

# Create app directory
echo "[3/7] Creating app directory..."
mkdir -p /root/localaitv1
cd /root/localaitv1

# Copy project files (you'll need to upload them)
# Or clone from your git repository:
echo "[4/7] Note: Upload your project files to /root/localaitv1/"
echo "    Option A: Git clone"
echo "    Option B: Upload via scp/sftp"

# Create necessary directories
echo "[5/7] Creating directories..."
mkdir -p inputs/{images,videos,audios}
mkdir -p outputs/{scripts,headlines,audios,reporters,item_video_cache,s3_inject_cache,bulletins}
mkdir -p assets/ads

# Set up FFmpeg
echo "[6/7] Checking FFmpeg..."
ffmpeg -version | head -1

# Create .env file from template
echo "[7/7] Creating .env file..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Please edit .env with your actual API keys!"
fi

echo ""
echo "============================================"
echo "Setup Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "1. Edit /root/localaitv1/.env with your API keys"
echo "2. Upload project files (if not using git)"
echo "3. Run: cd /root/localaitv1 && docker-compose -f docker-compose.prod.yml up -d"
echo ""
echo "To check status: docker ps"
echo "To view logs: docker logs localaitv_app"
echo "To restart: docker-compose -f docker-compose.prod.yml restart"
echo ""