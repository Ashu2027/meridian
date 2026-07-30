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
    if not defined MERIDIAN_BOOTSTRAPPED (
        set "MERIDIAN_BOOTSTRAPPED=1"
        call "%TARGET_DIR%\install.bat"
        exit /b 0
    )
)

cd /d "%APP_DIR%"

if exist "%APP_DIR%\.venv\Scripts\python.exe" (
    "%APP_DIR%\.venv\Scripts\python.exe" -c "import sys, encodings" >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
        goto INSTALL_DEPS
    )
)

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" (
        "%%D\python.exe" -c "import sys, encodings" >nul 2>&1
        if %errorlevel% equ 0 (
            "%%D\python.exe" -m venv "%APP_DIR%\.venv"
            if exist "%APP_DIR%\.venv\Scripts\python.exe" (
                set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
                goto INSTALL_DEPS
            )
        )
    )
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    python -c "import sys, encodings" >nul 2>&1
    if %errorlevel% equ 0 (
        python -m venv "%APP_DIR%\.venv"
        if exist "%APP_DIR%\.venv\Scripts\python.exe" (
            set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
            goto INSTALL_DEPS
        )
    )
)

echo [INFO] No working Python 3 found. Attempting automatic installation via winget...
winget --version >nul 2>&1
if %errorlevel% equ 0 (
    echo Installing Python 3.12 via winget...
    winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
    timeout /t 5 >nul
    python --version >nul 2>&1
    if %errorlevel% equ 0 (
        python -m venv "%APP_DIR%\.venv"
        if exist "%APP_DIR%\.venv\Scripts\python.exe" (
            set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
            goto INSTALL_DEPS
        )
    )
)

echo [ERROR] Python 3 was not found or is corrupted on your system.
echo Please install Python 3 manually from https://www.python.org/downloads/
pause
exit /b 1

:INSTALL_DEPS
echo.
echo [3/5] Installing dependencies...
"%PYTHON_EXE%" -m pip install -r "%APP_DIR%\requirements.txt"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b %errorlevel%
)

echo.
echo [4/5] Setting up global 'meridian' command shortcut...
if not exist "%APP_DIR%\bin" mkdir "%APP_DIR%\bin"
(
  echo @echo off
  echo "%APP_DIR%\.venv\Scripts\python.exe" "%APP_DIR%\main.py" %%*
) > "%APP_DIR%\bin\meridian.cmd"

(
  echo ^& "%APP_DIR%\.venv\Scripts\python.exe" "%APP_DIR%\main.py" $args
) > "%APP_DIR%\bin\meridian.ps1"

powershell -NoProfile -Command "$p = [Environment]::GetEnvironmentVariable('PATH', 'User'); if ($p -notlike '*%APP_DIR%\bin*') { [Environment]::SetEnvironmentVariable('PATH', $p + ';%APP_DIR%\bin', 'User') }" >nul 2>&1

echo.
echo =======================================================
echo  Setup Complete! Launching Meridian...
echo =======================================================
echo.
echo [5/5] Starting Meridian...
"%PYTHON_EXE%" "%APP_DIR%\main.py"

pause
