#!/bin/bash
set -e
echo "==> Installing system dependencies..."
apt-get update -qq && apt-get install -y -qq ffmpeg

echo "==> Installing Python dependencies..."
pip install --upgrade pip
pip install flask gunicorn requests

echo "==> Installing LATEST yt-dlp..."
pip install --upgrade yt-dlp

echo "==> yt-dlp version:"
yt-dlp --version

echo "==> Build complete ✅"
