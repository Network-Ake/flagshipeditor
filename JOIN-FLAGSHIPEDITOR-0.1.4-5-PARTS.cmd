@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "OUTPUT=FlagshipEditor-0.1.4-Windows.zip"
set "EXPECTED=b3963b55e02f79d2f37104bdd0b61903a0cfe8641d9e63b321fb19acf8b39099"
set "ACTUAL="

echo FlagshipEditor 0.1.4 - verified five-part joiner
echo No PowerShell. The output is rejected if one byte is wrong.
echo.

for %%F in (
  "FlagshipEditor-0.1.4-Windows.zip.part01"
  "FlagshipEditor-0.1.4-Windows.zip.part02"
  "FlagshipEditor-0.1.4-Windows.zip.part03"
  "FlagshipEditor-0.1.4-Windows.zip.part04"
  "FlagshipEditor-0.1.4-Windows.zip.part05"
) do if not exist "%%~F" (
  echo ERROR 10: Missing %%~F
  exit /b 10
)

if exist "%OUTPUT%" del /f /q "%OUTPUT%" || (
  echo ERROR 11: Close or rename the existing %OUTPUT%, then retry.
  exit /b 11
)

copy /b /y "FlagshipEditor-0.1.4-Windows.zip.part01"+"FlagshipEditor-0.1.4-Windows.zip.part02"+"FlagshipEditor-0.1.4-Windows.zip.part03"+"FlagshipEditor-0.1.4-Windows.zip.part04"+"FlagshipEditor-0.1.4-Windows.zip.part05" "%OUTPUT%" >nul || (
  echo ERROR 20: Windows could not join the five pieces.
  exit /b 20
)

for /f "tokens=1" %%H in ('certutil -hashfile "%OUTPUT%" SHA256 ^| findstr /R /I "^[0-9A-F][0-9A-F]*$"') do set "ACTUAL=%%H"
if not defined ACTUAL (
  del /f /q "%OUTPUT%" >nul 2>&1
  echo ERROR 30: Windows could not calculate the SHA-256 checksum.
  exit /b 30
)
if /I not "%ACTUAL%"=="%EXPECTED%" (
  del /f /q "%OUTPUT%" >nul 2>&1
  echo ERROR 31: A piece is incomplete or corrupted. The invalid ZIP was deleted.
  echo Expected: %EXPECTED%
  echo Actual:   %ACTUAL%
  exit /b 31
)

tar -tf "%OUTPUT%" >nul 2>&1 || (
  del /f /q "%OUTPUT%" >nul 2>&1
  echo ERROR 32: ZIP structure validation failed. The invalid ZIP was deleted.
  exit /b 32
)

echo.
echo SUCCESS - %OUTPUT% reconstructed and verified.
echo SHA-256: %EXPECTED%
echo Extract that ZIP, then run INSTALL-FLAGSHIPEDITOR.cmd with After Effects closed.
exit /b 0
