#!/usr/bin/env bash
set -e

echo "======================================================="
echo "Meridian Installation Setup (Linux / macOS)"
echo "======================================================="
echo ""

echo "[1/3] Creating virtual environment (.venv)..."
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python 3 is not installed or not in PATH."
    exit 1
fi

$PYTHON_CMD -m venv .venv

echo "[2/3] Installing dependencies..."
source .venv/bin/activate
pip install -r requirements.txt

echo ""
echo "======================================================="
echo "Installation Complete!"
echo "======================================================="
echo ""
echo "[3/3] Launching Meridian Setup Wizard..."
$PYTHON_CMD main.py
