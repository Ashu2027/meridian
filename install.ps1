# install.ps1 - Global One-Liner & Local Installer for Meridian (Windows)
$ErrorActionPreference = "Continue"

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "      Meridian Precision Outreach Installer           " -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

$targetDir = "$env:USERPROFILE\.meridian"

if (Test-Path "main.py") {
    $appDir = (Get-Item .).FullName
} else {
    Write-Host "[1/4] Setting up application in user profile ($targetDir)..." -ForegroundColor Green
    if (-not (Test-Path $targetDir)) {
        if (Get-Command git -ErrorAction SilentlyContinue) {
            Write-Host "Cloning repository from GitHub..." -ForegroundColor Yellow
            git clone https://github.com/Ashu2027/meridian.git $targetDir
        } else {
            Write-Host "[ERROR] Git is required for remote installation. Please install Git." -ForegroundColor Red
            Exit 1
        }
    } else {
        Write-Host "Existing installation found at $targetDir. Updating..." -ForegroundColor Yellow
        Push-Location $targetDir
        try { git pull } catch {}
        Pop-Location
    }
    $appDir = $targetDir
}

Set-Location $appDir

function Find-Python {
    if (Test-Path "$appDir\.venv\Scripts\python.exe") {
        return "$appDir\.venv\Scripts\python.exe"
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

Write-Host "[2/4] Checking virtual environment (.venv)..." -ForegroundColor Green
if (-not (Test-Path "$appDir\.venv\Scripts\python.exe")) {
    Write-Host "Creating .venv using '$pythonCmd'..." -ForegroundColor Yellow
    if ($pythonCmd -eq "py") {
        & py -3 -m venv "$appDir\.venv"
    } else {
        & $pythonCmd -m venv "$appDir\.venv"
    }
} else {
    Write-Host ".venv ready." -ForegroundColor Gray
}

$venvPython = "$appDir\.venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "[ERROR] Virtual environment Python executable not found." -ForegroundColor Red
    Exit 1
}

Write-Host "[3/4] Installing/updating dependencies in .venv..." -ForegroundColor Green
& $venvPython -m pip install -r "$appDir\requirements.txt"

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host " Setup Complete! Launching Meridian..." -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[4/4] Starting Meridian..." -ForegroundColor Green
& $venvPython "$appDir\main.py"
