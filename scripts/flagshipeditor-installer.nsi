; ============================================================
; FlagshipEditor v0.1.9 - NSIS Installer for Windows
; Built with NSIS 3.08 in Docker (Debian)
; ============================================================

!define APP_NAME "FlagshipEditor"
!define APP_VERSION "0.1.9"
!define APP_PUBLISHER "ake-studio"
!define APP_ID "com.akestudio.flagshipeditor"
!define APP_URL "https://github.com/Network-Ake/flagshipeditor"
!define CEP_PATH "$APPDATA\Adobe\CEP\extensions\${APP_ID}"
!define APP_PATH "$LOCALAPPDATA\ake-studio\FlagshipEditor\${APP_VERSION}"

SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "FlagshipEditor-${APP_VERSION}-Windows-Setup.exe"
InstallDir "$LOCALAPPDATA\ake-studio\FlagshipEditor"
RequestExecutionLevel user
ShowInstDetails show
ShowUnInstDetails show
BrandingText "ake-studio - FlagshipEditor ${APP_VERSION}"

VIProductVersion "0.1.9.0"
VIAddVersionKey "ProductName" "FlagshipEditor"
VIAddVersionKey "CompanyName" "ake-studio"
VIAddVersionKey "LegalCopyright" "(c) 2026 ake-studio"
VIAddVersionKey "FileDescription" "FlagshipEditor - AI Music Video Editor for After Effects"
VIAddVersionKey "FileVersion" "${APP_VERSION}"

!define MUI_ABORTWARNING
!define MUI_ICON "installer-icon.ico"
!define MUI_UNICON "installer-unicon.ico"
!define MUI_WELCOMEPAGE_TITLE "FlagshipEditor ${APP_VERSION} Setup"
!define MUI_WELCOMEPAGE_TEXT "This will install FlagshipEditor, the AI music video editor plugin for Adobe After Effects.$\r$\n$\r$\nClick Next to continue."
!define MUI_FINISHPAGE_TITLE "Installation Complete"
!define MUI_FINISHPAGE_TEXT "FlagshipEditor ${APP_VERSION} has been installed.$\r$\n$\r$\nOpen After Effects, then Window > Extensions > FlagshipEditor."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Show installation folder"
!define MUI_FINISHPAGE_RUN_FUNCTION "ShowInstallFolder"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Function ShowInstallFolder
  ExecShell "open" "$INSTDIR"
FunctionEnd

Function .onInit
  StrCpy $INSTDIR "$LOCALAPPDATA\ake-studio\FlagshipEditor"
FunctionEnd

; ============================================================
; Install
; ============================================================

Section "FlagshipEditor" SecMain
  SectionIn RO

  ; Create install directory
  CreateDirectory "$INSTDIR"
  SetOutPath "$INSTDIR"

  ; Write version marker
  FileOpen $0 "$INSTDIR\installed-version.txt" w
  FileWrite $0 "${APP_VERSION}"
  FileClose $0

  ; Extract the embedded ZIP payload
  DetailPrint "Extracting FlagshipEditor payload (226 MB)..."
  File "payload.zip"

  ; Use tar to extract (built into Windows 10 1803+)
  DetailPrint "Decompressing archive..."
  nsExec::ExecToLog 'tar -xf "$INSTDIR\payload.zip" -C "$INSTDIR"'
  Delete "$INSTDIR\payload.zip"

  ; Move files from extracted folder to install location
  DetailPrint "Installing CEP extension..."
  CreateDirectory "${CEP_PATH}"
  CopyFiles /SILENT "$INSTDIR\FlagshipEditor-0.1.9-Windows\dist\cep\*" "${CEP_PATH}"

  DetailPrint "Installing runtime (Python, FFmpeg)..."
  CreateDirectory "${APP_PATH}"
  CopyFiles /SILENT "$INSTDIR\FlagshipEditor-0.1.9-Windows\engine" "${APP_PATH}"
  CopyFiles /SILENT "$INSTDIR\FlagshipEditor-0.1.9-Windows\luts" "${APP_PATH}"
  CopyFiles /SILENT "$INSTDIR\FlagshipEditor-0.1.9-Windows\styles" "${APP_PATH}"
  CopyFiles /SILENT "$INSTDIR\FlagshipEditor-0.1.9-Windows\runtime" "${APP_PATH}"
  CopyFiles /SILENT "$INSTDIR\FlagshipEditor-0.1.9-Windows\scripts\Start-FlagshipEditor-Backend.cmd" "${APP_PATH}\scripts\"

  ; Copy payload checksums
  CopyFiles /SILENT "$INSTDIR\FlagshipEditor-0.1.9-Windows\payload-checksums.json" "$INSTDIR"

  ; Clean up extracted folder
  RMDir /r "$INSTDIR\FlagshipEditor-0.1.9-Windows"

  ; Write registry entries
  WriteRegStr HKCU "Software\ake-studio\FlagshipEditor" "Version" "${APP_VERSION}"
  WriteRegStr HKCU "Software\ake-studio\FlagshipEditor" "InstallPath" "$INSTDIR"
  WriteRegStr HKCU "Software\ake-studio\FlagshipEditor" "CEPPath" "${CEP_PATH}"
  WriteRegStr HKCU "Software\ake-studio\FlagshipEditor" "AppPath" "${APP_PATH}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlagshipEditor" "DisplayName" "FlagshipEditor ${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlagshipEditor" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlagshipEditor" "Publisher" "ake-studio"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlagshipEditor" "URLInfoAbout" "${APP_URL}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlagshipEditor" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlagshipEditor" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlagshipEditor" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlagshipEditor" "NoRepair" 1

  ; Create uninstaller
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Create Start Menu shortcuts
  CreateDirectory "$SMPROGRAMS\ake-studio"
  CreateShortcut "$SMPROGRAMS\ake-studio\FlagshipEditor.lnk" "${APP_PATH}\scripts\Start-FlagshipEditor-Backend.cmd" "" "" "" SW_SHOWMINIMIZED "" "Start FlagshipEditor Backend"
  CreateShortcut "$SMPROGRAMS\ake-studio\Uninstall FlagshipEditor.lnk" "$INSTDIR\uninstall.exe" "" "" "" SW_SHOWNORMAL "" "Uninstall FlagshipEditor"

  DetailPrint ""
  DetailPrint "FlagshipEditor ${APP_VERSION} installed successfully."
  DetailPrint "CEP Extension: ${CEP_PATH}"
  DetailPrint "Runtime: ${APP_PATH}"
  DetailPrint ""
  DetailPrint "Open After Effects > Window > Extensions > FlagshipEditor"
SectionEnd

; ============================================================
; Uninstall
; ============================================================

Section "Uninstall"
  ; Stop backend if running
  nsExec::ExecToLog 'taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq FlagshipEditor*"'
  Sleep 1000

  ; Remove CEP extension
  RMDir /r /REBOOTOK "${CEP_PATH}"

  ; Remove runtime and engine
  RMDir /r /REBOOTOK "${APP_PATH}"
  RMDir /r /REBOOTOK "$LOCALAPPDATA\ake-studio\FlagshipEditor"

  ; Remove registry entries
  DeleteRegKey HKCU "Software\ake-studio\FlagshipEditor"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlagshipEditor"

  ; Remove Start Menu shortcuts
  Delete "$SMPROGRAMS\ake-studio\FlagshipEditor.lnk"
  Delete "$SMPROGRAMS\ake-studio\Uninstall FlagshipEditor.lnk"
  RMDir "$SMPROGRAMS\ake-studio"

  ; Remove uninstaller and install dir
  Delete "$INSTDIR\uninstall.exe"
  Delete "$INSTDIR\installed-version.txt"
  Delete "$INSTDIR\payload-checksums.json"
  RMDir /r "$INSTDIR"

  DetailPrint "FlagshipEditor has been uninstalled."
SectionEnd
