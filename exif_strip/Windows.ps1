# Go to the folder containing /exif
Set-Location "$PSScriptRoot"

# 1. Install Python if missing (requires winget on Win10/11)
if (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Python via winget..."
    winget install -e --id Python.Python.3 --accept-package-agreements --accept-source-agreements
}

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# Pick python executable
$python = (Get-Command py -ErrorAction SilentlyContinue) ? "py -3" : "python"

# 2. Create venv
& $python -m venv exif\.venv

# 3. Install dependencies
& .\exif\.venv\Scripts\pip install --upgrade pip
& .\exif\.venv\Scripts\pip install flask Pillow pillow-heif piexif

# 4. Launch
& .\exif\.venv\Scripts\python .\exif\EXIF_STRIP.py
