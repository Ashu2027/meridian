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
    if [ -z "$MERIDIAN_BOOTSTRAPPED" ]; then
        export MERIDIAN_BOOTSTRAPPED=1
        exec bash "$APP_DIR/install.sh"
    fi
fi

cd "$APP_DIR"

find_python() {
    if command -v python3 &>/dev/null && python3 -c "import sys, encodings" &>/dev/null; then
        echo "python3"
    elif command -v python &>/dev/null && python -c "import sys, encodings" &>/dev/null; then
        echo "python"
    else
        echo ""
    fi
}

PYTHON_SYSTEM=$(find_python)

if [ -z "$PYTHON_SYSTEM" ]; then
    echo "[INFO] Python 3 missing. Attempting automatic installation..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -y && sudo apt-get install -y python3 python3-venv python3-pip
    elif command -v brew &>/dev/null; then
        brew install python3
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3 python3-pip
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm python python-pip
    fi
    PYTHON_SYSTEM=$(find_python)
fi

if [ -z "$PYTHON_SYSTEM" ]; then
    echo "[ERROR] Python 3 was not found. Please install python3 and python3-venv."
    exit 1
fi

echo "[2/5] Creating virtual environment (.venv)..."
VENV_PYTHON="$APP_DIR/.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ] || ! "$VENV_PYTHON" -c "import sys, encodings" &>/dev/null; then
    rm -rf "$APP_DIR/.venv"
    $PYTHON_SYSTEM -m venv "$APP_DIR/.venv" || {
        if command -v apt-get &>/dev/null; then
            sudo apt-get install -y python3-venv
            $PYTHON_SYSTEM -m venv "$APP_DIR/.venv"
        fi
    }
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
