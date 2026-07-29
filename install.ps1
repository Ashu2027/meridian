# install.ps1 - End-to-End Automated Meridian Setup for Windows (PowerShell)
$ErrorActionPreference = "Continue"

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host " Meridian End-to-End Setup (Windows PowerShell)" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

function Find-Python {
    if (Test-Path ".venv\Scripts\python.exe") {
        return ".venv\Scripts\python.exe"
    }

    $commands = @("py", "python", "python3")
    foreach ($cmd in $commands) {
        try {
            $ver = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $ver -notlike "*Microsoft Store*") {
                return $cmd
            }
        } catch {}
    }

    $searchPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe",
        "$env:ProgramFiles\Python*\python.exe",
        "C:\Python*\python.exe"
    )

    foreach ($pathPattern in $searchPaths) {
        $found = Get-Item $pathPattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            return $found.FullName
        }
    }

    return $null
}

$pythonCmd = Find-Python

if (-not $pythonCmd) {
    Write-Host "[ERROR] Python 3 was not found on your system." -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/downloads/ and ensure 'Add Python to PATH' is checked." -ForegroundColor Yellow
    Exit 1
}

Write-Host "[1/3] Checking virtual environment (.venv)..." -ForegroundColor Green
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv using '$pythonCmd'..." -ForegroundColor Yellow
    if ($pythonCmd -eq "py") {
        & py -3 -m venv .venv
    } else {
        & $pythonCmd -m venv .venv
    }
} else {
    Write-Host ".venv already exists. Reusing environment." -ForegroundColor Gray
}

$venvPython = ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "[ERROR] Virtual environment Python executable not found at $venvPython." -ForegroundColor Red
    Exit 1
}

Write-Host "[2/3] Installing/updating dependencies in .venv..." -ForegroundColor Green
& $venvPython -m pip install -r requirements.txt

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host " Setup Complete! Launching Meridian..." -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[3/3] Running Meridian..." -ForegroundColor Green
& $venvPython main.py
