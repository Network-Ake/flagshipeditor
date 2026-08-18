# FlagshipEditor — Windows Setup Script
# Run this on your Windows 11 machine to set up the dev environment

Write-Host "=== FlagshipEditor Windows Setup ===" -ForegroundColor Cyan

# 1. Check Node.js
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "Installing Node.js 20 LTS..." -ForegroundColor Yellow
    winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
    Write-Host "Node.js installed. Restart your terminal and run this script again." -ForegroundColor Green
    exit 0
} else {
    Write-Host "Node.js found: $(node --version)" -ForegroundColor Green
}

# 2. Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Installing Python 3.12..." -ForegroundColor Yellow
    winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Write-Host "Python installed. Restart your terminal and run this script again." -ForegroundColor Green
    exit 0
} else {
    Write-Host "Python found: $(python --version)" -ForegroundColor Green
}

# 3. Check FFmpeg
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    Write-Host "FFmpeg not found. Installing via winget..." -ForegroundColor Yellow
    winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "FFmpeg found: $(ffmpeg --version | Select-Object -First 1)" -ForegroundColor Green
}

# 4. Check Git
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Host "Installing Git..." -ForegroundColor Yellow
    winget install Git.Git --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "Git found: $(git --version)" -ForegroundColor Green
}

# 5. Install Python dependencies
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install fastapi uvicorn librosa opencv-python scikit-learn pydantic numpy scipy

# 6. Install Yarn
Write-Host "Installing Yarn..." -ForegroundColor Yellow
npm install -g yarn

# 7. Enable PlayerDebugMode for unsigned extensions
Write-Host "Enabling PlayerDebugMode (for unsigned CEP extensions)..." -ForegroundColor Yellow
$regKey = "HKCU:\Software\Adobe\CSXS.12"
if (-not (Test-Path $regKey)) {
    New-Item -Path $regKey -Force
}
Set-ItemProperty -Path $regKey -Name "PlayerDebugMode" -Value "1" -Type String
Write-Host "PlayerDebugMode enabled for CEP 12" -ForegroundColor Green

# 8. Clone repo (if not already in current dir)
if (-not (Test-Path "flagshipeditor/package.json")) {
    Write-Host "Cloning FlagshipEditor repo..." -ForegroundColor Yellow
    # TODO: Replace with actual GitHub repo URL
    # git clone https://github.com/akestudio/flagshipeditor.git
    Write-Host "Repo URL TBD. For now, copy the project folder from the Mac mini." -ForegroundColor Yellow
}

# 9. Install Node dependencies
if (Test-Path "flagshipeditor/package.json") {
    Write-Host "Installing Node dependencies..." -ForegroundColor Yellow
    cd flagshipeditor
    yarn install
    Write-Host "Dependencies installed!" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Setup Complete! ===" -ForegroundColor Cyan
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Open After Effects 2024+" -ForegroundColor White
Write-Host "  2. Window > Extensions > FlagshipEditor" -ForegroundColor White
Write-Host "  3. Start the Python backend: cd engine && python server.py" -ForegroundColor White
Write-Host "  4. Import clips + music, select style, click GENERATE" -ForegroundColor White