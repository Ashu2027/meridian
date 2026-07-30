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

function Test-Python($cmd) {
    try {
        $res = & $cmd -c "import sys, encodings; print(sys.version_info[0])" 2>&1
        if ($LASTEXITCODE -eq 0 -and ($res -like "*3*" -or $res -eq "3")) {
            return $true
        }
    } catch {}
    return $false
}

function Find-Python {
    if (Test-Path "$appDir\.venv\Scripts\python.exe") {
        if (Test-Python "$appDir\.venv\Scripts\python.exe") {
            return "$appDir\.venv\Scripts\python.exe"
        }
    }

    $searchPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "C:\Python3*\python.exe"
    )
    foreach ($pathPattern in $searchPaths) {
        $found = Get-Item $pathPattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found -and (Test-Python $found.FullName)) {
            return $found.FullName
        }
    }

    $commands = @("python", "python3", "py")
    foreach ($cmd in $commands) {
        try {
            $ver = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $ver -notlike "*Microsoft Store*" -and (Test-Python $cmd)) {
                return $cmd
            }
        } catch {}
    }

    return $null
}

$pythonCmd = Find-Python

if (-not $pythonCmd) {
    Write-Host "[INFO] No working Python 3 installation detected. Attempting automatic installation..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Python 3.12 via winget..." -ForegroundColor Yellow
        winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
        Start-Sleep -Seconds 5
        $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH", "User")
        $pythonCmd = Find-Python
    }
}

if (-not $pythonCmd) {
    Write-Host "[ERROR] Python 3 was not found or is corrupted on your system." -ForegroundColor Red
    Write-Host "Please install Python 3 manually from https://www.python.org/downloads/ and ensure 'Add Python to PATH' is checked." -ForegroundColor Yellow
    Exit 1
}

Write-Host "[2/5] Creating virtual environment (.venv)..." -ForegroundColor Green
$venvPython = "$appDir\.venv\Scripts\python.exe"

if (-not (Test-Path $venvPython) -or -not (Test-Python $venvPython)) {
    Write-Host "Creating .venv using '$pythonCmd'..." -ForegroundColor Yellow
    if (Test-Path "$appDir\.venv") {
        Remove-Item -Recurse -Force "$appDir\.venv" -ErrorAction SilentlyContinue
    }
    
    & $pythonCmd -m venv "$appDir\.venv"
    if (-not (Test-Path $venvPython)) {
        & py -3 -m venv "$appDir\.venv"
    }
} else {
    Write-Host ".venv ready and verified." -ForegroundColor Gray
}

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

Write-Host "[4/5] Setting up global 'meridian' command shortcut..." -ForegroundColor Green
$binDir = "$appDir\bin"
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir | Out-Null }
Set-Content -Path "$binDir\meridian.cmd" -Value "@echo off`r`n`"$appDir\.venv\Scripts\python.exe`" `"$appDir\main.py`" %*"
Set-Content -Path "$binDir\meridian.ps1" -Value "& `"$appDir\.venv\Scripts\python.exe`" `"$appDir\main.py`" `$args"

$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$binDir*") {
    try {
        [Environment]::SetEnvironmentVariable("PATH", "$userPath;$binDir", "User")
        $env:PATH = "$env:PATH;$binDir"
        Write-Host "Added $binDir to User PATH." -ForegroundColor Yellow
    } catch {}
}

Write-Host "[5/5] Starting Meridian..." -ForegroundColor Green
& $venvPython "$appDir\main.py"
