#Requires -Version 5.1
<#+
.SYNOPSIS
Installs the self-contained FlagshipEditor extension and analysis backend.

.DESCRIPTION
Validates and installs the bundled CEP extension, portable Python runtime,
Python dependencies, FFmpeg, and FFprobe for the current Windows user.
No Python, Node.js, winget, administrator rights, or network connection is
required on the destination computer.
#>

[CmdletBinding()]
param([string]$ProjectRoot = "")

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $scriptPath = $MyInvocation.MyCommand.Path
    if ([string]::IsNullOrWhiteSpace($scriptPath)) {
        throw "Cannot determine the installer location. Run INSTALL-FLAGSHIPEDITOR.cmd from the extracted package."
    }
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $scriptPath)
}

$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$ExtensionId = "com.akestudio.flagshipeditor"
$BackendId = "com.akestudio.flagshipeditor.backend"
$ExpectedVersion = "0.1.3"
$CepRoot = Join-Path $env:APPDATA "Adobe\CEP\extensions"
$ExtensionDir = Join-Path $CepRoot $ExtensionId
$ApplicationDir = Join-Path $env:LOCALAPPDATA "ake-studio\FlagshipEditor"
$BackendDir = Join-Path $ApplicationDir "backend"
$RuntimeDir = Join-Path $ApplicationDir "runtime"
$RuntimePythonDir = Join-Path $RuntimeDir "python"
$RuntimeBinDir = Join-Path $RuntimeDir "bin"
$PayloadManifest = Join-Path $ProjectRoot "payload-checksums.json"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Copy-Tree([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Required package folder is missing: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    & robocopy $Source $Destination /E /PURGE /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Copy from '$Source' to '$Destination' failed (robocopy exit code $LASTEXITCODE)."
    }
}

function Get-BackendHealth {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:18791/health" -TimeoutSec 2
    } catch {
        return $null
    }
}

function Test-PayloadIntegrity {
    if (-not (Test-Path -LiteralPath $PayloadManifest)) {
        throw "payload-checksums.json is missing. Extract the complete ZIP and rerun the installer."
    }
    $entries = @(Get-Content -LiteralPath $PayloadManifest -Raw | ConvertFrom-Json)
    if ($entries.Count -lt 10) {
        throw "The package checksum manifest is invalid or incomplete."
    }
    foreach ($entry in $entries) {
        $relativePath = [string]$entry.path
        $expectedHash = ([string]$entry.sha256).ToLowerInvariant()
        $filePath = Join-Path $ProjectRoot ($relativePath.Replace("/", "\"))
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
            throw "Package file is missing: $relativePath"
        }
        $actualHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "Package integrity check failed: $relativePath"
        }
    }
}

function Stop-InstalledBackend {
    $applicationPrefix = $ApplicationDir.TrimEnd("\") + "\"
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($applicationPrefix, [StringComparison]::OrdinalIgnoreCase)
    })
    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($processes.Count -gt 0) {
        Start-Sleep -Milliseconds 750
    }
}

Write-Step "Validating the complete offline package"
Test-PayloadIntegrity

$requiredFiles = @(
    "dist\cep\CSXS\manifest.xml",
    "dist\cep\main\index.html",
    "dist\cep\jsx\index.js",
    "runtime\python\python.exe",
    "runtime\python\pythonw.exe",
    "runtime\bin\ffmpeg.exe",
    "runtime\bin\ffprobe.exe",
    "engine\server.py",
    "engine\VERSION"
)
foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $relativePath) -PathType Leaf)) {
        throw "Required package file is missing: $relativePath"
    }
}

if (Get-Process -Name "AfterFX" -ErrorAction SilentlyContinue) {
    throw "After Effects is running. Close it completely, then run this installer again."
}

Write-Step "Stopping an older FlagshipEditor backend"
Stop-InstalledBackend
$portHealth = Get-BackendHealth
if ($portHealth) {
    throw "Port 18791 is already used by another application. Close that application, then rerun the installer."
}

Write-Step "Installing the After Effects extension"
Copy-Tree (Join-Path $ProjectRoot "dist\cep") $ExtensionDir
foreach ($folder in @("styles", "luts")) {
    Copy-Tree (Join-Path $ProjectRoot $folder) (Join-Path $ExtensionDir $folder)
}

foreach ($csxsVersion in @("9", "10", "11", "12", "13")) {
    $registryPath = "HKCU:\Software\Adobe\CSXS.$csxsVersion"
    New-Item -Path $registryPath -Force | Out-Null
    New-ItemProperty -Path $registryPath -Name "PlayerDebugMode" -Value "1" -PropertyType String -Force | Out-Null
}

Write-Step "Installing the bundled analysis runtime"
New-Item -ItemType Directory -Path $ApplicationDir -Force | Out-Null
Copy-Tree (Join-Path $ProjectRoot "engine") $BackendDir
Copy-Tree (Join-Path $ProjectRoot "runtime\python") $RuntimePythonDir
Copy-Tree (Join-Path $ProjectRoot "runtime\bin") $RuntimeBinDir

Write-Step "Creating the backend launcher"
$launcherPs1 = Join-Path $ApplicationDir "Start-FlagshipEditor-Backend.ps1"
$launcherCmd = Join-Path $ApplicationDir "Start-FlagshipEditor-Backend.cmd"
$logDir = Join-Path $ApplicationDir "logs"
$pythonwPath = (Join-Path $RuntimePythonDir "pythonw.exe").Replace("'", "''")
$backendPath = $BackendDir.Replace("'", "''")
$runtimeBinPath = $RuntimeBinDir.Replace("'", "''")
$logPath = $logDir.Replace("'", "''")
$launcherContent = @"
`$ErrorActionPreference = 'Stop'
`$backendId = '$BackendId'
`$expectedVersion = '$ExpectedVersion'
function Get-FlagshipHealth {
    try { return Invoke-RestMethod -Uri 'http://127.0.0.1:18791/health' -TimeoutSec 2 } catch { return `$null }
}
`$health = Get-FlagshipHealth
if (`$health) {
    if (`$health.appId -eq `$backendId -and `$health.version -eq `$expectedVersion) {
        Write-Host 'FlagshipEditor backend is already running.' -ForegroundColor Green
        exit 0
    }
    throw 'Port 18791 is occupied by another application or an incompatible FlagshipEditor backend.'
}
`$logDir = '$logPath'
New-Item -ItemType Directory -Path `$logDir -Force | Out-Null
`$env:PATH = '$runtimeBinPath;' + `$env:PATH
`$env:FLAGSHIPEDITOR_FFPROBE = '$runtimeBinPath\ffprobe.exe'
`$process = Start-Process -FilePath '$pythonwPath' -ArgumentList @('server.py') -WorkingDirectory '$backendPath' -WindowStyle Hidden -RedirectStandardOutput (Join-Path `$logDir 'backend.log') -RedirectStandardError (Join-Path `$logDir 'backend-error.log') -PassThru
for (`$attempt = 0; `$attempt -lt 120; `$attempt++) {
    Start-Sleep -Milliseconds 500
    `$health = Get-FlagshipHealth
    if (`$health) {
        if (`$health.appId -ne `$backendId -or `$health.version -ne `$expectedVersion) {
            Stop-Process -Id `$process.Id -Force -ErrorAction SilentlyContinue
            throw 'A different service answered on FlagshipEditor port 18791.'
        }
        if (-not `$health.librosa -or -not `$health.opencv -or -not `$health.shot_selector -or -not `$health.ffprobe -or -not `$health.ffmpeg) {
            Stop-Process -Id `$process.Id -Force -ErrorAction SilentlyContinue
            throw 'The bundled backend failed its dependency self-check. See backend-error.log.'
        }
        Write-Host "FlagshipEditor backend started (PID `$(`$process.Id))." -ForegroundColor Green
        exit 0
    }
    if (`$process.HasExited) {
        throw "Backend exited with code `$(`$process.ExitCode). See `$logDir\backend-error.log"
    }
}
Stop-Process -Id `$process.Id -Force -ErrorAction SilentlyContinue
throw "Backend did not become healthy in 60 seconds. See `$logDir\backend-error.log"
"@
Set-Content -LiteralPath $launcherPs1 -Value $launcherContent -Encoding UTF8
$cmdContent = "@echo off`r`npowershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$launcherPs1`"`r`nif errorlevel 1 pause`r`n"
Set-Content -LiteralPath $launcherCmd -Value $cmdContent -Encoding ASCII

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FlagshipEditor"
New-Item -ItemType Directory -Path $startMenu -Force | Out-Null
Copy-Item -LiteralPath $launcherCmd -Destination (Join-Path $startMenu "Start FlagshipEditor Backend.cmd") -Force

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$runCommand = "powershell.exe -NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcherPs1`""
New-Item -Path $runKey -Force | Out-Null
New-ItemProperty -Path $runKey -Name "FlagshipEditorBackend" -Value $runCommand -PropertyType String -Force | Out-Null

Write-Step "Starting and verifying the bundled backend"
& $launcherPs1

Write-Host "`nFlagshipEditor $ExpectedVersion installed successfully." -ForegroundColor Green
Write-Host "CEP extension: $ExtensionDir"
Write-Host "Application:   $ApplicationDir"
Write-Host "`nRestart After Effects, then open Window > Extensions > FlagshipEditor."
