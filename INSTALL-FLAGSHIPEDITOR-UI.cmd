@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "FLAGSHIP_VERSION=2.0.0"
set "EXTENSION_ID=com.akestudio.flagshipeditor"
set "CEP_PARENT=%APPDATA%\Adobe\CEP\extensions"
set "CEP_FINAL=%CEP_PARENT%\%EXTENSION_ID%"
set "CEP_STAGE=%CEP_PARENT%\%EXTENSION_ID%.installing-%RANDOM%"
set "CEP_BACKUP=%CEP_PARENT%\%EXTENSION_ID%.previous-%RANDOM%"

echo FlagshipEditor %FLAGSHIP_VERSION% - UI-only installer disabled
echo The panel and backend must always be installed together.
echo Run INSTALL-FLAGSHIPEDITOR.cmd from the full package.
echo.
exit /b 78

if not exist "dist\cep\CSXS\manifest.xml" goto :incomplete
if not exist "dist\cep\main\index.html" goto :incomplete
if not exist "dist\cep\jsx\index.js" goto :incomplete
findstr /C:"ExtensionBundleVersion" "dist\cep\CSXS\manifest.xml" | findstr /C:"%FLAGSHIP_VERSION%" >nul || goto :incomplete
tasklist /FI "IMAGENAME eq AfterFX.exe" 2>nul | find /I "AfterFX.exe" >nul && goto :aeopen

mkdir "%CEP_PARENT%" >nul 2>&1
robocopy "%CD%\dist\cep" "%CEP_STAGE%" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :copyfailed
if exist "styles" robocopy "%CD%\styles" "%CEP_STAGE%\styles" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :copyfailed
if exist "luts" robocopy "%CD%\luts" "%CEP_STAGE%\luts" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :copyfailed

if exist "%CEP_FINAL%" move "%CEP_FINAL%" "%CEP_BACKUP%" >nul || goto :copyfailed
move "%CEP_STAGE%" "%CEP_FINAL%" >nul || goto :rollback
for %%V in (9 10 11 12 13) do reg add "HKCU\Software\Adobe\CSXS.%%V" /v PlayerDebugMode /t REG_SZ /d 1 /f >nul || goto :rollback

if exist "%CEP_BACKUP%" rmdir /s /q "%CEP_BACKUP%"
echo.
echo SUCCESS - UI %FLAGSHIP_VERSION% installed.
echo Restart After Effects and open Window ^> Extensions ^> FlagshipEditor.
exit /b 0

:rollback
if exist "%CEP_FINAL%" rmdir /s /q "%CEP_FINAL%"
if exist "%CEP_BACKUP%" move "%CEP_BACKUP%" "%CEP_FINAL%" >nul
:copyfailed
if exist "%CEP_STAGE%" rmdir /s /q "%CEP_STAGE%"
echo ERROR 31: Windows could not copy the panel. The previous panel was restored.
exit /b 31
:aeopen
echo ERROR 20: Close After Effects completely, then run this file again.
exit /b 20
:incomplete
echo ERROR 10: Package incomplete or version mismatch. Extract the whole ZIP again.
exit /b 10
