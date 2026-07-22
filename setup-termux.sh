#!/data/data/com.termux/files/usr/bin/bash
# One-shot setup for Termux on Android.
set -e

echo "==> Updating Termux packages"
pkg update -y
pkg install -y python

echo "==> Installing Python dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo
echo "Setup complete."
echo "Next:"
echo "  1. cp config.example.json config.json"
echo "  2. put your Discord user token in config.json (or export DISCORD_TOKEN=...)"
echo "  3. python -m orbquest list"
echo "  4. python -m orbquest run"
