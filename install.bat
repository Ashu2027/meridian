@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo       Meridian Precision Outreach Installer
echo =======================================================
echo.

set "TARGET_DIR=%USERPROFILE%\.meridian"

if exist "main.py" (
    set "APP_DIR=%CD%"
) else (
    echo [1/4] Setting up application in user profile (%TARGET_DIR%)...
    if not exist "%TARGET_DIR%" (
        git --version >nul 2>&1
        if %errorlevel% equ 0 (
            echo Cloning repository from GitHub...
            git clone https://github.com/Ashu2027/meridian.git "%TARGET_DIR%"
        ) else (
            echo [ERROR] Git is required for installation. Please install Git.
            pause
            exit /b 1
        )
    ) else (
        echo Existing installation found at %TARGET_DIR%. Updating...
        cd /d "%TARGET_DIR%"
        git pull >nul 2>&1
    )
    set "APP_DIR=%TARGET_DIR%"
)

cd /d "%APP_DIR%"

if exist "%APP_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
    goto INSTALL_DEPS
)

py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    py -3 -m venv "%APP_DIR%\.venv"
    if exist "%APP_DIR%\.venv\Scripts\python.exe" (
        set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
        goto INSTALL_DEPS
    )
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    python -m venv "%APP_DIR%\.venv"
    if exist "%APP_DIR%\.venv\Scripts\python.exe" (
        set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
        goto INSTALL_DEPS
    )
)

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        "%%D\python.exe" -m venv "%APP_DIR%\.venv"
        if exist "%APP_DIR%\.venv\Scripts\python.exe" (
            set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
            goto INSTALL_DEPS
        )
    )
)

echo [ERROR] Python 3 was not found. Please install Python 3.
pause
exit /b 1

:INSTALL_DEPS
echo.
echo [3/4] Installing dependencies...
"%PYTHON_EXE%" -m pip install -r "%APP_DIR%\requirements.txt"
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
echo [4/4] Starting Meridian...
"%PYTHON_EXE%" "%APP_DIR%\main.py"

pause
