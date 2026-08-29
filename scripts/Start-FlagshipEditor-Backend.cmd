@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "FLAGSHIP_VERSION=3.1.0"
set "BACKEND_ID=com.akestudio.flagshipeditor.backend"
set "PYTHON=%CD%\runtime\python\python.exe"
set "PYTHONW=%CD%\runtime\python\pythonw.exe"
set "BACKEND=%CD%\engine"
set "RUNTIME_BIN=%CD%\runtime\bin"
set "LOG_DIR=%CD%\logs"
set "PATH=%RUNTIME_BIN%;%PATH%"
set "FLAGSHIPEDITOR_FFPROBE=%RUNTIME_BIN%\ffprobe.exe"
set "FLAGSHIPEDITOR_FFMPEG=%RUNTIME_BIN%\ffmpeg.exe"

if not exist "%PYTHON%" goto :runtime_missing
if not exist "%PYTHONW%" goto :runtime_missing
if not exist "%BACKEND%\server.py" goto :runtime_missing
if not exist "%RUNTIME_BIN%\ffprobe.exe" goto :runtime_missing
mkdir "%LOG_DIR%" >nul 2>&1

call :CheckHealth
if not errorlevel 1 (
  echo FlagshipEditor backend %FLAGSHIP_VERSION% is already healthy.
  exit /b 0
)

pushd "%BACKEND%"
start "FlagshipEditor Backend" /b "%PYTHONW%" "server.py" 1>>"%LOG_DIR%\backend.log" 2>>"%LOG_DIR%\backend-error.log"
popd

for /L %%I in (1,1,120) do (
  call :CheckHealth
  if not errorlevel 1 goto :healthy
  >nul 2>&1 ping 127.0.0.1 -n 2
)

echo ERROR 61: Backend did not become healthy in 120 seconds.
echo Log: %LOG_DIR%\backend-error.log
if exist "%LOG_DIR%\backend-error.log" type "%LOG_DIR%\backend-error.log"
call :StopStartedBackend
exit /b 61

:healthy
echo FlagshipEditor backend %FLAGSHIP_VERSION% is healthy.
exit /b 0

:CheckHealth
rem mkdir is atomic: it fails when the folder already exists, so the probe
rem always lands in a fresh private folder even when %RANDOM% repeats.
set /a HEALTH_TRIES=0
:HealthTempDir
set /a HEALTH_TRIES+=1
if %HEALTH_TRIES% GTR 20 exit /b 1
set "HEALTH_DIR=%TEMP%\flagshipeditor-health-%RANDOM%%RANDOM%"
mkdir "%HEALTH_DIR%" >nul 2>&1 || goto :HealthTempDir
set "HEALTH_FILE=%HEALTH_DIR%\health.json"
curl.exe -fsS --max-time 3 "http://127.0.0.1:18791/health" >"%HEALTH_FILE%" 2>nul
if not exist "%HEALTH_FILE%" goto :HealthFail
findstr /C:"%BACKEND_ID%" "%HEALTH_FILE%" >nul 2>&1
if errorlevel 1 goto :HealthFail
findstr /C:"%FLAGSHIP_VERSION%" "%HEALTH_FILE%" >nul 2>&1
if errorlevel 1 goto :HealthFail
findstr /C:"\"librosa\":true" "%HEALTH_FILE%" >nul 2>&1
if errorlevel 1 goto :HealthFail
findstr /C:"\"opencv\":true" "%HEALTH_FILE%" >nul 2>&1
if errorlevel 1 goto :HealthFail
findstr /C:"\"shot_selector\":true" "%HEALTH_FILE%" >nul 2>&1
if errorlevel 1 goto :HealthFail
findstr /C:"\"ffprobe\":true" "%HEALTH_FILE%" >nul 2>&1
if errorlevel 1 goto :HealthFail
findstr /C:"\"ffmpeg\":true" "%HEALTH_FILE%" >nul 2>&1
if errorlevel 1 goto :HealthFail
rmdir /s /q "%HEALTH_DIR%" >nul 2>&1
exit /b 0

:HealthFail
rmdir /s /q "%HEALTH_DIR%" >nul 2>&1
exit /b 1

:StopStartedBackend
set "BACKEND_PID="
set "PID_FILE=%BACKEND%\.flagshipeditor.pid"
if not exist "%PID_FILE%" exit /b 0
rem Validate before expansion so corrupt PID-file text cannot become CMD syntax.
"%PYTHON%" -c "import pathlib,sys;s=pathlib.Path(sys.argv[1]).read_text(encoding='ascii').strip();raise SystemExit(0 if s.isdigit() and int(s) in range(1,4294967296) else 1)" "%PID_FILE%" >nul 2>&1
if errorlevel 1 exit /b 1
set /p BACKEND_PID=<"%PID_FILE%"
tasklist /FI "PID eq %BACKEND_PID%" /FI "IMAGENAME eq pythonw.exe" /NH 2>nul | find /I "pythonw.exe" >nul
if errorlevel 1 (
  del /q "%PID_FILE%" >nul 2>&1
  exit /b 0
)
taskkill /PID %BACKEND_PID% /T /F >nul 2>&1
for /L %%W in (1,1,10) do (
  tasklist /FI "PID eq %BACKEND_PID%" /FI "IMAGENAME eq pythonw.exe" /NH 2>nul | find /I "pythonw.exe" >nul
  if errorlevel 1 (
    del /q "%PID_FILE%" >nul 2>&1
    exit /b 0
  )
  >nul 2>&1 ping 127.0.0.1 -n 2
)
exit /b 1

:runtime_missing
echo ERROR 60: The bundled FlagshipEditor runtime is incomplete.
exit /b 60
