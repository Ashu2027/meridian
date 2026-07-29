@echo off
echo =======================================================
echo Meridian Installation Setup (Windows)
echo =======================================================
echo.

echo [1/3] Creating virtual environment (.venv)...
python -m venv .venv
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create virtual environment. Ensure python is installed.
    pause
    exit /b %errorlevel%
)

echo [2/3] Installing dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b %errorlevel%
)

echo.
echo =======================================================
echo Installation Complete!
echo =======================================================
echo.
echo [3/3] Launching Meridian Setup Wizard...
python main.py

pause
