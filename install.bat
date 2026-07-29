@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo  Meridian End-to-End Setup (Windows)
echo =======================================================
echo.

rem 1. Check if .venv\Scripts\python.exe already exists
if exist ".venv\Scripts\python.exe" (
    echo [INFO] Existing virtual environment found in .venv.
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    goto INSTALL_DEPS
)

rem 2. Try py launcher
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Found Python launcher (py). Creating .venv...
    py -3 -m venv .venv
    if exist ".venv\Scripts\python.exe" (
        set "PYTHON_EXE=.venv\Scripts\python.exe"
        goto INSTALL_DEPS
    )
)

rem 3. Try python command
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Found python command. Creating .venv...
    python -m venv .venv
    if exist ".venv\Scripts\python.exe" (
        set "PYTHON_EXE=.venv\Scripts\python.exe"
        goto INSTALL_DEPS
    )
)

rem 4. Try python3 command
python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Found python3 command. Creating .venv...
    python3 -m venv .venv
    if exist ".venv\Scripts\python.exe" (
        set "PYTHON_EXE=.venv\Scripts\python.exe"
        goto INSTALL_DEPS
    )
)

rem 5. Check AppData Python paths
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        echo [INFO] Found Python at %%D\python.exe. Creating .venv...
        "%%D\python.exe" -m venv .venv
        if exist ".venv\Scripts\python.exe" (
            set "PYTHON_EXE=.venv\Scripts\python.exe"
            goto INSTALL_DEPS
        )
    )
)

rem 6. Check C:\Python* paths
for /d %%D in ("C:\Python*") do (
    if exist "%%D\python.exe" (
        echo [INFO] Found Python at %%D\python.exe. Creating .venv...
        "%%D\python.exe" -m venv .venv
        if exist ".venv\Scripts\python.exe" (
            set "PYTHON_EXE=.venv\Scripts\python.exe"
            goto INSTALL_DEPS
        )
    )
)

echo [ERROR] Python 3 was not found in PATH or standard installation directories.
echo Please install Python 3 from https://www.python.org/downloads/ and ensure "Add Python to PATH" is checked during installation.
pause
exit /b 1

:INSTALL_DEPS
echo.
echo [2/3] Installing dependencies in .venv...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b %errorlevel%
)

echo.
echo =======================================================
echo  Setup Complete! Launching Meridian...
echo =======================================================
echo.
echo [3/3] Running Meridian...
"%PYTHON_EXE%" main.py

pause
