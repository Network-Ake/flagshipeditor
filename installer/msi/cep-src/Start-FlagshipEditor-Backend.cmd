@echo off
rem FlagshipEditor 3.0.0 - bridge from the CEP panel to the installed backend.
rem
rem The panel looks for this file inside its own extension folder and shells out
rem to it. The backend itself lives under Program Files, so all this does is find
rem the install and hand off to the windowless launcher.
setlocal EnableExtensions DisableDelayedExpansion

set "INSTALL_DIR="
for /f "tokens=2,*" %%A in ('reg query "HKLM\Software\ake-studio\FlagshipEditor" /v InstallDir /reg:64 2^>nul ^| findstr /I /C:"InstallDir"') do set "INSTALL_DIR=%%B"

if defined INSTALL_DIR if exist "%INSTALL_DIR%\Start-FlagshipEditor-Backend.vbs" goto :launch
if defined ProgramW6432 set "INSTALL_DIR=%ProgramW6432%\FlagshipEditor"
if exist "%INSTALL_DIR%\Start-FlagshipEditor-Backend.vbs" goto :launch
set "INSTALL_DIR=%ProgramFiles%\FlagshipEditor"
if exist "%INSTALL_DIR%\Start-FlagshipEditor-Backend.vbs" goto :launch

echo ERROR 60: FlagshipEditor is not installed. Run FlagshipEditor-3.0.0-Windows.msi again.
exit /b 60

:launch
start "" /b wscript.exe //nologo "%INSTALL_DIR%\Start-FlagshipEditor-Backend.vbs"
exit /b 0
