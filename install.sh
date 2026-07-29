#!/usr/bin/env bash
set -e

echo "======================================================="
echo " Meridian End-to-End Setup (Linux / macOS)"
echo "======================================================="
echo ""

if [ -f ".venv/bin/python" ]; then
    echo "[INFO] Existing virtual environment found in .venv."
    VENV_PYTHON=".venv/bin/python"
else
    if command -v python3 &>/dev/null; then
        PYTHON_SYSTEM="python3"
    elif command -v python &>/dev/null; then
        PYTHON_SYSTEM="python"
    else
        echo "[ERROR] Python 3 was not found. Please install python3."
        exit 1
    fi

    echo "[1/3] Creating virtual environment (.venv) using $PYTHON_SYSTEM..."
    $PYTHON_SYSTEM -m venv .venv
    VENV_PYTHON=".venv/bin/python"
fi

echo "[2/3] Installing dependencies..."
"$VENV_PYTHON" -m pip install -r requirements.txt

echo ""
echo "======================================================="
echo " Setup Complete! Launching Meridian..."
echo "======================================================="
echo ""
echo "[3/3] Running Meridian..."
"$VENV_PYTHON" main.py
