#Requires -Version 5.1
<#+
.SYNOPSIS
Installs FlagshipEditor for the current Windows user.

.DESCRIPTION
Installs missing prerequisites with winget, builds the CEP extension, creates an
isolated Python environment for the backend, installs the extension in Adobe's
per-user CEP directory, and creates an idempotent backend launcher.

Run from an extracted FlagshipEditor project. Administrator rights are not
normally required because all FlagshipEditor files are installed per-user.
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$SkipPrerequisiteInstall,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExtensionId = "com.akestudio.flagshipeditor"
$CepRoot = Join-Path $env:APPDATA "Adobe\CEP\extensions"
$ExtensionDir = Join-Path $CepRoot $ExtensionId
$ApplicationDir = Join-Path $env:LOCALAPPDATA "ake-studio\FlagshipEditor"
$BackendDir = Join-Path $ApplicationDir "backend"
$VenvDir = Join-Path $BackendDir ".venv"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Find-Command([string[]]$Names) {
    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    return $null
}

function Install-WingetPackage([string]$Id, [string]$DisplayName) {
    if ($SkipPrerequisiteInstall) {
        throw "$DisplayName is missing and -SkipPrerequisiteInstall was specified."
    }
    $winget = Find-Command @("winget.exe", "winget")
    if (-not $winget) {
        throw "$DisplayName is missing and winget is unavailable. Install App Installer from Microsoft Store, then rerun this script."
    }

    Write-Host "Installing $DisplayName..." -ForegroundColor Yellow
    & $winget install --id $Id --exact --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install $DisplayName (exit code $LASTEXITCODE)."
    }
    Refresh-ProcessPath
}

function Assert-Version([string]$Executable, [string[]]$Arguments, [version]$Minimum, [string]$DisplayName) {
    $output = (& $Executable @Arguments 2>&1 | Out-String).Trim()
    $match = [regex]::Match($output, "(\d+\.\d+(?:\.\d+)?)")
    if (-not $match.Success -or [version]$match.Groups[1].Value -lt $Minimum) {
        throw "$DisplayName $Minimum or newer is required. Found: $output"
    }
    Write-Host "$DisplayName found: $output" -ForegroundColor Green
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments, [string]$Description) {
    Write-Host $Description -ForegroundColor Yellow
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed (exit code $LASTEXITCODE)."
    }
}

function Copy-Tree([string]$Source, [string]$Destination, [string[]]$ExcludedDirectories = @()) {
    if (-not (Test-Path $Source)) { return }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $arguments = @($Source, $Destination, "/E", "/PURGE", "/R:2", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
    if ($ExcludedDirectories.Count -gt 0) {
        $arguments += "/XD"
        $arguments += $ExcludedDirectories
    }
    & robocopy @arguments | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Copy from '$Source' to '$Destination' failed (robocopy exit code $LASTEXITCODE)."
    }
}

$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
if (-not (Test-Path (Join-Path $ProjectRoot "package.json"))) {
    throw "FlagshipEditor package.json was not found at '$ProjectRoot'. Copy/extract the complete project and rerun the script."
}
if (-not (Test-Path (Join-Path $ProjectRoot "CSXS\manifest.xml"))) {
    throw "CSXS\manifest.xml is missing from '$ProjectRoot'."
}

Write-Step "Checking Windows prerequisites"
$node = Find-Command @("node.exe", "node")
if (-not $node) {
    Install-WingetPackage "OpenJS.NodeJS.LTS" "Node.js LTS"
    $node = Find-Command @("node.exe", "node")
}
if (-not $node) { throw "Node.js was installed but is not available. Open a new PowerShell window and rerun this script." }
Assert-Version $node @("--version") ([version]"20.0") "Node.js"

$npm = Find-Command @("npm.cmd", "npm")
if (-not $npm) { throw "npm was not found. Repair the Node.js installation and rerun this script." }

$python = Find-Command @("py.exe", "python.exe", "python")
if (-not $python) {
    Install-WingetPackage "Python.Python.3.12" "Python 3.12"
    $python = Find-Command @("py.exe", "python.exe", "python")
}
if (-not $python) { throw "Python was installed but is not available. Open a new PowerShell window and rerun this script." }
$pythonArgs = if ([IO.Path]::GetFileName($python) -ieq "py.exe") { @("-3") } else { @() }
Assert-Version $python ($pythonArgs + @("--version")) ([version]"3.10") "Python"

$ffmpeg = Find-Command @("ffmpeg.exe", "ffmpeg")
if (-not $ffmpeg) {
    Install-WingetPackage "Gyan.FFmpeg" "FFmpeg"
    $ffmpeg = Find-Command @("ffmpeg.exe", "ffmpeg")
}
if (-not $ffmpeg) { throw "FFmpeg was installed but is not available. Open a new PowerShell window and rerun this script." }
Write-Host "FFmpeg found: $((& $ffmpeg -version | Select-Object -First 1))" -ForegroundColor Green

if (-not $SkipBuild) {
    Write-Step "Installing JavaScript dependencies and building the CEP extension"
    Push-Location $ProjectRoot
    try {
        if (Test-Path (Join-Path $ProjectRoot "package-lock.json")) {
            Invoke-Checked $npm @("ci", "--no-audit", "--no-fund") "Installing locked npm dependencies"
        } else {
            Invoke-Checked $npm @("install", "--no-audit", "--no-fund") "Installing npm dependencies"
        }
        Invoke-Checked $npm @("run", "build") "Building FlagshipEditor"
    } finally {
        Pop-Location
    }
}

$distDir = Join-Path $ProjectRoot "dist\cep"
if (-not (Test-Path (Join-Path $distDir "main\index.html"))) {
    throw "Build output dist\main\index.html is missing. Rerun without -SkipBuild and resolve any build errors."
}
if (-not (Test-Path (Join-Path $distDir "jsx\index.js"))) {
    throw "Build output dist\jsx\index.js is missing. Rerun without -SkipBuild and resolve any build errors."
}

Write-Step "Installing the Python backend"
New-Item -ItemType Directory -Path $ApplicationDir -Force | Out-Null
Copy-Tree (Join-Path $ProjectRoot "engine") $BackendDir @(".venv", "__pycache__")

if (-not (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
    Invoke-Checked $python ($pythonArgs + @("-m", "venv", $VenvDir)) "Creating isolated Python environment"
}
$venvPython = Join-Path $VenvDir "Scripts\python.exe"
Invoke-Checked $venvPython @("-m", "pip", "install", "--upgrade", "pip") "Updating pip"
Invoke-Checked $venvPython @("-m", "pip", "install", "-r", (Join-Path $BackendDir "requirements.txt")) "Installing Python dependencies"

Write-Step "Installing the CEP extension for the current user"
New-Item -ItemType Directory -Path $ExtensionDir -Force | Out-Null
Copy-Tree (Join-Path $ProjectRoot "CSXS") (Join-Path $ExtensionDir "CSXS")
Copy-Tree $distDir $ExtensionDir
foreach ($folder in @("styles", "luts", "assets")) {
    Copy-Tree (Join-Path $ProjectRoot $folder) (Join-Path $ExtensionDir $folder)
}

foreach ($csxsVersion in @("9", "10", "11", "12")) {
    $registryPath = "HKCU:\Software\Adobe\CSXS.$csxsVersion"
    New-Item -Path $registryPath -Force | Out-Null
    New-ItemProperty -Path $registryPath -Name "PlayerDebugMode" -Value "1" -PropertyType String -Force | Out-Null
}

Write-Step "Creating the backend launcher"
$launcherPs1 = Join-Path $ApplicationDir "Start-FlagshipEditor-Backend.ps1"
$launcherCmd = Join-Path $ApplicationDir "Start-FlagshipEditor-Backend.cmd"
$logDir = Join-Path $ApplicationDir "logs"
$escapedPython = $venvPython.Replace("'", "''")
$escapedServer = (Join-Path $BackendDir "server.py").Replace("'", "''")
$escapedBackend = $BackendDir.Replace("'", "''")
$escapedLogDir = $logDir.Replace("'", "''")
$launcherContent = @"
`$ErrorActionPreference = 'Stop'
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:18791/health' -TimeoutSec 2 | Out-Null
    Write-Host 'FlagshipEditor backend is already running.' -ForegroundColor Green
    exit 0
} catch { }
`$logDir = '$escapedLogDir'
New-Item -ItemType Directory -Path `$logDir -Force | Out-Null
`$process = Start-Process -FilePath '$escapedPython' -ArgumentList @('$escapedServer') -WorkingDirectory '$escapedBackend' -WindowStyle Hidden -RedirectStandardOutput (Join-Path `$logDir 'backend.log') -RedirectStandardError (Join-Path `$logDir 'backend-error.log') -PassThru
for (`$attempt = 0; `$attempt -lt 20; `$attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:18791/health' -TimeoutSec 2 | Out-Null
        Write-Host "FlagshipEditor backend started (PID `$(`$process.Id))." -ForegroundColor Green
        exit 0
    } catch {
        if (`$process.HasExited) { throw "Backend exited with code `$(`$process.ExitCode). See `$logDir\backend-error.log" }
    }
}
throw "Backend did not become healthy in 10 seconds. See `$logDir\backend-error.log"
"@
Set-Content -LiteralPath $launcherPs1 -Value $launcherContent -Encoding UTF8
$cmdContent = "@echo off`r`npowershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$launcherPs1`"`r`npause`r`n"
Set-Content -LiteralPath $launcherCmd -Value $cmdContent -Encoding ASCII

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FlagshipEditor"
New-Item -ItemType Directory -Path $startMenu -Force | Out-Null
Copy-Item -LiteralPath $launcherCmd -Destination (Join-Path $startMenu "Start FlagshipEditor Backend.cmd") -Force

Write-Host "`nFlagshipEditor installation completed successfully." -ForegroundColor Green
Write-Host "CEP extension: $ExtensionDir"
Write-Host "Backend:       $BackendDir"
Write-Host "Launcher:      $launcherCmd"
Write-Host "`nRestart After Effects, then open Window > Extensions > FlagshipEditor."
Write-Host "Start the backend from the Windows Start menu before using AI analysis."
