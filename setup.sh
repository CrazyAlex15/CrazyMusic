#!/usr/bin/env bash
# CrazyMusic — Raspberry Pi 4 setup / repair script.
# Run from inside the CrazyMusic folder:  bash setup.sh
set -e

echo "==> Installing system dependencies (ffmpeg, opus, nodejs)..."
sudo apt update
# ffmpeg = audio transcoding | libopus0 = voice encoding | nodejs = REQUIRED by yt-dlp for YouTube
sudo apt install -y ffmpeg libopus0 nodejs

echo "==> Setting up Python virtual environment..."
if [ ! -d venv ]; then
    python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

echo "==> Installing / upgrading Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Upgrading yt-dlp to the very latest (YouTube changes constantly)..."
pip install --upgrade yt-dlp

echo ""
echo "==> Versions:"
echo -n "    ffmpeg : "; ffmpeg -version 2>/dev/null | head -n1 || echo "NOT FOUND"
echo -n "    node   : "; node --version 2>/dev/null || echo "NOT FOUND"
echo -n "    yt-dlp : "; yt-dlp --version 2>/dev/null || echo "NOT FOUND"
echo ""
echo "Done. Make sure your .env file contains:  DISCORD_TOKEN=your_token_here"
echo "Then start the bot with:  source venv/bin/activate && python main.py"
