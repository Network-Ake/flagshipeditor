@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem PUSHD maps a UNC package path to a temporary drive letter. CD /D leaves CMD
rem in its previous directory when the installer is launched from a network share.
pushd "%~dp0" >nul 2>&1
if errorlevel 1 (
  echo ERROR 9: Could not access the extracted package folder.
  echo Copy the ZIP to a folder you can read, extract it completely, and retry.
  endlocal & exit /b 9
)
set "PACKAGE_ROOT_PUSHED=1"

set "FLAGSHIP_VERSION=3.1.0"
set "EXTENSION_ID=com.akestudio.flagshipeditor"
set "BACKEND_ID=com.akestudio.flagshipeditor.backend"
set "PROJECT_ROOT=%CD%"
set "EXIT_CODE=0"

echo ============================================================
echo FlagshipEditor %FLAGSHIP_VERSION% - Native Windows installer
echo No PowerShell. No downloads. No system Python required.
echo ============================================================
echo.

if defined FLAGSHIPEDITOR_TEST_ROOT (
  set "CEP_PARENT=%FLAGSHIPEDITOR_TEST_ROOT%\Adobe\CEP\extensions"
  set "APP_PARENT=%FLAGSHIPEDITOR_TEST_ROOT%\ake-studio\FlagshipEditor"
  set "SKIP_REGISTRY=1"
) else (
  set "CEP_PARENT=%APPDATA%\Adobe\CEP\extensions"
  set "APP_PARENT=%LOCALAPPDATA%\ake-studio\FlagshipEditor"
)
set "CEP_FINAL=%CEP_PARENT%\%EXTENSION_ID%"
set "CEP_STAGE=%CEP_PARENT%\%EXTENSION_ID%.installing-%RANDOM%"
set "CEP_BACKUP=%CEP_PARENT%\%EXTENSION_ID%.previous-%RANDOM%"
set "APP_FINAL=%APP_PARENT%\%FLAGSHIP_VERSION%"
set "APP_STAGE=%APP_PARENT%\%FLAGSHIP_VERSION%.installing-%RANDOM%"
set "APP_BACKUP=%APP_PARENT%\%FLAGSHIP_VERSION%.previous-%RANDOM%"

call :RequireFile "dist\cep\CSXS\manifest.xml" || goto :fail
call :RequireFile "dist\cep\main\index.html" || goto :fail
call :RequireFile "dist\cep\jsx\index.js" || goto :fail
call :RequireFile "runtime\python\python.exe" || goto :fail
call :RequireFile "runtime\python\pythonw.exe" || goto :fail
call :RequireFile "runtime\bin\ffmpeg.exe" || goto :fail
call :RequireFile "runtime\bin\ffprobe.exe" || goto :fail
call :RequireFile "engine\server.py" || goto :fail
call :RequireFile "engine\self_test.py" || goto :fail
call :RequireFile "engine\fixtures\prores-422-standard.mov" || goto :fail
call :RequireFile "engine\fixtures\prores-422-hq.mov" || goto :fail
call :RequireFile "engine\VERSION" || goto :fail
call :RequireFile "scripts\Start-FlagshipEditor-Backend.cmd" || goto :fail

findstr /C:"ExtensionBundleVersion" "dist\cep\CSXS\manifest.xml" | findstr /C:"%FLAGSHIP_VERSION%" >nul || (
  call :Error 12 "The CEP manifest version does not match this installer. Re-extract the complete package."
  goto :fail
)
set /p ENGINE_VERSION=<"engine\VERSION"
if not "%ENGINE_VERSION%"=="%FLAGSHIP_VERSION%" (
  call :Error 13 "The backend version does not match this installer. Re-extract the complete package."
  goto :fail
)

where robocopy.exe >nul 2>&1 || (
  call :Error 14 "Windows robocopy.exe is missing."
  goto :fail
)
where curl.exe >nul 2>&1 || (
  call :Error 15 "Windows curl.exe is missing. Install current Windows updates and retry."
  goto :fail
)

if not defined FLAGSHIPEDITOR_TEST_ROOT (
  tasklist /FI "IMAGENAME eq AfterFX.exe" 2>nul | find /I "AfterFX.exe" >nul && (
    call :Error 20 "After Effects is running. Close it completely, then run this installer again."
    goto :fail
  )
)

echo [1/6] Stopping the installed FlagshipEditor backend...
call :StopInstalledBackend
if errorlevel 1 (
  call :Error 21 "Could not stop the installed FlagshipEditor backend. Its runtime was left untouched."
  goto :fail
)

echo [2/6] Staging the CEP panel...
mkdir "%CEP_PARENT%" >nul 2>&1
call :RemoveTree "%CEP_STAGE%"
if errorlevel 1 (
  call :Error 30 "Could not clear the previous CEP staging folder."
  goto :fail
)
robocopy "%PROJECT_ROOT%\dist\cep" "%CEP_STAGE%" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  call :Error 31 "Could not stage the CEP panel."
  goto :fail
)
for %%D in (styles luts) do (
  if exist "%PROJECT_ROOT%\%%D" (
    robocopy "%PROJECT_ROOT%\%%D" "%CEP_STAGE%\%%D" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 (
      call :Error 32 "Could not stage %%D."
      goto :fail
    )
  )
)
call :RequireAbsoluteFile "%CEP_STAGE%\main\index.html" || goto :fail
call :RequireAbsoluteFile "%CEP_STAGE%\CSXS\manifest.xml" || goto :fail

echo [3/6] Activating the CEP panel...
if exist "%CEP_FINAL%" (
  move "%CEP_FINAL%" "%CEP_BACKUP%" >nul || (
    call :Error 33 "Could not back up the previous CEP panel."
    goto :fail
  )
)
move "%CEP_STAGE%" "%CEP_FINAL%" >nul || (
  if exist "%CEP_BACKUP%" move "%CEP_BACKUP%" "%CEP_FINAL%" >nul
  call :Error 34 "Could not activate the new CEP panel."
  goto :fail
)

if not defined SKIP_REGISTRY (
  for %%V in (9 10 11 12 13) do (
    reg add "HKCU\Software\Adobe\CSXS.%%V" /v PlayerDebugMode /t REG_SZ /d 1 /f >nul || (
      call :Error 35 "Could not enable Adobe CEP debug mode."
      goto :rollback_cep
    )
  )
)

echo [4/6] Staging the offline analysis backend...
mkdir "%APP_PARENT%" >nul 2>&1
call :RemoveTree "%APP_STAGE%"
if errorlevel 1 (
  call :Error 40 "Could not clear the previous backend staging folder."
  goto :rollback_cep
)
mkdir "%APP_STAGE%" >nul 2>&1
for %%D in (engine runtime) do (
  robocopy "%PROJECT_ROOT%\%%D" "%APP_STAGE%\%%D" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
  if errorlevel 8 (
    call :Error 41 "Could not stage %%D."
    goto :rollback_cep
  )
)
copy /y "%PROJECT_ROOT%\scripts\Start-FlagshipEditor-Backend.cmd" "%APP_STAGE%\Start-FlagshipEditor-Backend.cmd" >nul || (
  call :Error 42 "Could not stage the backend launcher."
  goto :rollback_cep
)
call :RequireAbsoluteFile "%APP_STAGE%\runtime\python\python.exe" || goto :rollback_cep
call :RequireAbsoluteFile "%APP_STAGE%\runtime\bin\ffprobe.exe" || goto :rollback_cep

echo [5/6] Testing packaged ProRes 422 Standard and HQ decoding...
set "FLAGSHIPEDITOR_FFPROBE=%APP_STAGE%\runtime\bin\ffprobe.exe"
set "FLAGSHIPEDITOR_FFMPEG=%APP_STAGE%\runtime\bin\ffmpeg.exe"
set "FLAGSHIPEDITOR_THUMBNAILS=%TEMP%\flagshipeditor-self-test-%RANDOM%"
"%APP_STAGE%\runtime\python\python.exe" "%APP_STAGE%\engine\self_test.py"
if errorlevel 1 (
  call :Error 45 "The exact packaged Python/OpenCV/FFmpeg runtime could not decode ProRes 422 Standard and HQ."
  goto :rollback_cep
)
if exist "%FLAGSHIPEDITOR_THUMBNAILS%" rmdir /s /q "%FLAGSHIPEDITOR_THUMBNAILS%"
set "FLAGSHIPEDITOR_THUMBNAILS="

if exist "%APP_FINAL%" (
  move "%APP_FINAL%" "%APP_BACKUP%" >nul || (
    call :Error 43 "Could not back up the previous backend."
    goto :rollback_cep
  )
)
move "%APP_STAGE%" "%APP_FINAL%" >nul || (
  if exist "%APP_BACKUP%" move "%APP_BACKUP%" "%APP_FINAL%" >nul
  call :Error 44 "Could not activate the new backend."
  goto :rollback_cep
)

echo [6/6] Starting and verifying the bundled backend...
set "HEALTH_FILE=%TEMP%\flagshipeditor-health-%RANDOM%.json"
curl.exe -fsS --max-time 3 "http://127.0.0.1:18791/health" >"%HEALTH_FILE%" 2>nul
if exist "%HEALTH_FILE%" (
  findstr /C:"%BACKEND_ID%" "%HEALTH_FILE%" >nul && (
    echo Stopping the previous FlagshipEditor backend...
    curl.exe -fsS --max-time 3 -X POST "http://127.0.0.1:18791/shutdown" >nul 2>&1
    >nul 2>&1 ping 127.0.0.1 -n 3
  )
  del /q "%HEALTH_FILE%" >nul 2>&1
)
call "%APP_FINAL%\Start-FlagshipEditor-Backend.cmd"
if errorlevel 1 (
  call :Error 51 "The backend self-test failed. Read the log path printed above."
  goto :rollback_app
)

if not defined SKIP_REGISTRY (
  reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v FlagshipEditorBackend /t REG_SZ /d "\"%APP_FINAL%\Start-FlagshipEditor-Backend.cmd\"" /f >nul || (
    call :Error 52 "Could not register backend startup."
    goto :rollback_app
  )
)

echo.
echo ============================================================
echo SUCCESS - FlagshipEditor %FLAGSHIP_VERSION% is installed.
echo CEP panel: %CEP_FINAL%
echo Backend:   %APP_FINAL%
echo Restart After Effects, then open Window ^> Extensions ^> FlagshipEditor.
echo ============================================================
call :RemoveTree "%CEP_BACKUP%"
call :RemoveTree "%APP_BACKUP%"
call :LeavePackageRoot
endlocal & exit /b 0

:rollback_app
rem Never remove a runtime tree while its pythonw.exe can still have files open.
call :StopInstalledBackend
if errorlevel 1 (
  set "EXIT_CODE=71"
  echo ERROR 71: Rollback could not stop the new backend. Backup preserved at:
  echo %APP_BACKUP%
  goto :rollback_cep
)
call :RemoveTree "%APP_FINAL%"
if errorlevel 1 (
  set "EXIT_CODE=72"
  echo ERROR 72: Rollback could not remove the inactive backend. Backup preserved at:
  echo %APP_BACKUP%
  goto :rollback_cep
)
if exist "%APP_BACKUP%" (
  move "%APP_BACKUP%" "%APP_FINAL%" >nul || (
    set "EXIT_CODE=73"
    echo ERROR 73: The previous backend could not be restored. It remains at:
    echo %APP_BACKUP%
  )
)
:rollback_cep
call :RemoveTree "%CEP_FINAL%"
if not errorlevel 1 if exist "%CEP_BACKUP%" move "%CEP_BACKUP%" "%CEP_FINAL%" >nul
goto :fail

:StopInstalledBackend
if not exist "%APP_FINAL%" exit /b 0
set "BACKEND_PID="
set "PID_FILE=%APP_FINAL%\engine\.flagshipeditor.pid"
if exist "%PID_FILE%" (
  rem Validate before expansion so corrupt PID-file text cannot become CMD syntax.
  "%PROJECT_ROOT%\runtime\python\python.exe" -c "import pathlib,sys;s=pathlib.Path(sys.argv[1]).read_text(encoding='ascii').strip();raise SystemExit(0 if s.isdigit() and int(s) in range(1,4294967296) else 1)" "%PID_FILE%" >nul 2>&1
  if errorlevel 1 exit /b 1
  set /p BACKEND_PID=<"%PID_FILE%"
)

rem Ask only a verified FlagshipEditor service to stop. A healthy response also
rem binds the PID file to the process answering on the dedicated local port.
set "HEALTH_FILE=%TEMP%\flagshipeditor-stop-health-%RANDOM%.json"
curl.exe -fsS --max-time 3 "http://127.0.0.1:18791/health" >"%HEALTH_FILE%" 2>nul
if not defined BACKEND_PID (
  if exist "%HEALTH_FILE%" findstr /C:"%BACKEND_ID%" "%HEALTH_FILE%" >nul
  if not errorlevel 1 (
    del /q "%HEALTH_FILE%" >nul 2>&1
    exit /b 1
  )
  if exist "%HEALTH_FILE%" del /q "%HEALTH_FILE%" >nul 2>&1
  exit /b 0
)
if exist "%HEALTH_FILE%" (
  "%PROJECT_ROOT%\runtime\python\python.exe" -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));raise SystemExit(0 if d.get('appId')=='%BACKEND_ID%' and d.get('processId')==int(sys.argv[2]) else 1)" "%HEALTH_FILE%" "%BACKEND_PID%" >nul 2>&1
  if not errorlevel 1 curl.exe -fsS --max-time 3 -X POST "http://127.0.0.1:18791/shutdown" >nul 2>&1
)
if exist "%HEALTH_FILE%" del /q "%HEALTH_FILE%" >nul 2>&1

call :WaitForPidExit "%BACKEND_PID%" 20
if not errorlevel 1 (
  if exist "%PID_FILE%" del /q "%PID_FILE%" >nul 2>&1
  exit /b 0
)

rem An unhealthy backend may not answer HTTP. The fallback is deliberately
rem guarded by its private PID file, numeric validation and pythonw.exe image.
tasklist /FI "PID eq %BACKEND_PID%" /FI "IMAGENAME eq pythonw.exe" /NH 2>nul | find /I "pythonw.exe" >nul
if errorlevel 1 exit /b 1
taskkill /PID %BACKEND_PID% /T /F >nul 2>&1
if errorlevel 1 exit /b 1
call :WaitForPidExit "%BACKEND_PID%" 20
if errorlevel 1 exit /b 1
if exist "%PID_FILE%" del /q "%PID_FILE%" >nul 2>&1
exit /b 0

:WaitForPidExit
rem Wait up to %~2 iterations of ~1 second each for pythonw.exe to exit.
rem On Windows, Python runtime file handles can take several seconds to
rem release after taskkill /T /F, especially for embedded distributions.
for /L %%W in (1,1,%~2) do (
  tasklist /FI "PID eq %~1" /FI "IMAGENAME eq pythonw.exe" /NH 2>nul | find /I "pythonw.exe" >nul
  if errorlevel 1 exit /b 0
  >nul 2>&1 ping 127.0.0.1 -n 2
)
exit /b 1

:RemoveTree
rem Try up to 8 times with a 1-second pause. Windows file handles can
rem linger after process termination, especially for Python runtimes on
rem network shares or antivirus-scanned directories.
if not exist "%~1" exit /b 0
for /L %%R in (1,1,8) do (
  rmdir /s /q "%~1" >nul 2>&1
  if not exist "%~1" exit /b 0
  >nul 2>&1 ping 127.0.0.1 -n 2
)
exit /b 1

:LeavePackageRoot
if defined PACKAGE_ROOT_PUSHED popd
set "PACKAGE_ROOT_PUSHED="
exit /b 0

:RequireFile
if exist "%PROJECT_ROOT%\%~1" exit /b 0
call :Error 10 "Required package file is missing: %~1"
exit /b 1

:RequireAbsoluteFile
if exist "%~1" exit /b 0
call :Error 11 "Staged file is missing: %~1"
exit /b 1

:Error
set "EXIT_CODE=%~1"
echo.
echo ERROR %~1: %~2
exit /b 0

:fail
call :RemoveTree "%CEP_STAGE%"
call :RemoveTree "%APP_STAGE%"
if "%EXIT_CODE%"=="0" set "EXIT_CODE=99"
echo Installation stopped safely. Error code: %EXIT_CODE%
set "FINAL_EXIT_CODE=%EXIT_CODE%"
call :LeavePackageRoot
endlocal & exit /b %FINAL_EXIT_CODE%
