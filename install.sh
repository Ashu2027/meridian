#!/usr/bin/env bash
set -e

echo "======================================================="
echo "      Meridian Precision Outreach Installer           "
echo "======================================================="
echo ""

TARGET_DIR="$HOME/.meridian"

if [ -f "main.py" ]; then
    APP_DIR="$(pwd)"
else
    echo "[1/4] Setting up application in user profile ($TARGET_DIR)..."
    if [ ! -d "$TARGET_DIR" ]; then
        if command -v git &>/dev/null; then
            echo "Cloning repository from GitHub..."
            git clone https://github.com/Ashu2027/meridian.git "$TARGET_DIR"
        else
            echo "[ERROR] Git is required for remote installation. Please install git."
            exit 1
        fi
    else
        echo "Existing installation found at $TARGET_DIR. Updating..."
        cd "$TARGET_DIR" && git pull || true
    fi
    APP_DIR="$TARGET_DIR"
fi

cd "$APP_DIR"

if [ -f "$APP_DIR/.venv/bin/python" ]; then
    VENV_PYTHON="$APP_DIR/.venv/bin/python"
else
    if command -v python3 &>/dev/null; then
        PYTHON_SYSTEM="python3"
    elif command -v python &>/dev/null; then
        PYTHON_SYSTEM="python"
    else
        echo "[ERROR] Python 3 was not found. Please install python3."
        exit 1
    fi

    echo "[2/4] Creating virtual environment (.venv)..."
    $PYTHON_SYSTEM -m venv "$APP_DIR/.venv"
    VENV_PYTHON="$APP_DIR/.venv/bin/python"
fi

echo "[3/4] Installing dependencies..."
"$VENV_PYTHON" -m pip install -r "$APP_DIR/requirements.txt"

echo "[4/5] Setting up global 'meridian' command shortcut..."
mkdir -p "$HOME/.local/bin"
cat << EOF > "$HOME/.local/bin/meridian"
#!/bin/sh
exec "$APP_DIR/.venv/bin/python" "$APP_DIR/main.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/meridian"

echo ""
echo "======================================================="
echo " Setup Complete! Launching Meridian..."
echo "======================================================="
echo ""
echo "[5/5] Starting Meridian..."
"$VENV_PYTHON" "$APP_DIR/main.py"
