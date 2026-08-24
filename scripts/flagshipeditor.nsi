; ============================================================
; FlagshipEditor v2.0.0 - NSIS Installer for Windows
; Professional installer with uninstaller, registry entries,
; and CEP extension registration.
; ============================================================

!define APP_NAME "FlagshipEditor"
!define APP_VERSION "2.0.0"
!define APP_PUBLISHER "ake-studio"
!define APP_ID "com.akestudio.flagshipeditor"
!define APP_URL "https://github.com/Network-Ake/flagshipeditor"
!define CEP_PATH "$APPDATA\Adobe\CEP\extensions\${APP_ID}"
!define APP_PATH "$LOCALAPPDATA\ake-studio\FlagshipEditor\${APP_VERSION}"

; --- Compression ---
SetCompressor /SOLID lzma

; --- Modern UI ---
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

; --- Settings ---
Name "${APP_NAME} ${APP_VERSION}"
OutFile "..\..\Downloads\FlagshipEditor-${APP_VERSION}-Windows-Setup.exe"
InstallDir "$LOCALAPPDATA\ake-studio\FlagshipEditor"
RequestExecutionLevel user
ShowInstDetails show
ShowUnInstDetails show
BrandingText "ake-studio - FlagshipEditor ${APP_VERSION}"

; --- Version Info ---
VIProductVersion "2.0.0.0"
VIAddVersionKey "ProductName" "FlagshipEditor"
VIAddVersionKey "CompanyName" "ake-studio"
VIAddVersionKey "LegalCopyright" "(c) 2026 ake-studio"
VIAddVersionKey "FileDescription" "FlagshipEditor - AI Music Video Editor for After Effects"
VIAddVersionKey "FileVersion" "${APP_VERSION}"

; --- MUI Settings ---
!define MUI_ABORTWARNING
!define MUI_ICON "installer-icon.ico"
!define MUI_UNICON "installer-unicon.ico"
!define MUI_WELCOMEPAGE_TITLE "FlagshipEditor ${APP_VERSION} Setup"
!define MUI_WELCOMEPAGE_TEXT "This will install FlagshipEditor, the AI music video editor plugin for Adobe After Effects.$\r$\n$\r$\nClick Install to continue."
!define MUI_FINISHPAGE_TITLE "Installation Complete"
!define MUI_FINISHPAGE_TEXT "FlagshipEditor ${APP_VERSION} has been installed.$\r$\n$\r$\nOpen After Effects, then Window > Extensions > FlagshipEditor."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Show installation folder"
!define MUI_FINISHPAGE_RUN_FUNCTION "ShowInstallFolder"

; --- Pages ---
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; --- Languages ---
!insertmacro MUI_LANGUAGE "English"

; ============================================================
; Functions
; ============================================================

Function ShowInstallFolder
  ExecShell "open" "$INSTDIR"
FunctionEnd

Function .onInit
  StrCpy $INSTDIR "$LOCALAPPDATA\ake-studio\FlagshipEditor"
FunctionEnd

; ============================================================
; Install Section
; ============================================================

Section "FlagshipEditor" SecMain
  SectionIn RO

  SetOutPath "$INSTDIR"

  ; --- Write version marker ---
  FileOpen $0 "$INSTDIR\installed-version.txt" w
  FileWrite $0 "${APP_VERSION}"
  FileClose $0

  ; --- Copy CEP extension files ---
  SetOutPath "${CEP_PATH}"
  File /r "dist\cep\*.*"

  ; --- Copy engine files ---
  SetOutPath "${APP_PATH}\engine"
  File /r "engine\*.*"

  ; --- Copy LUTs ---
  SetOutPath "${APP_PATH}\luts"
  File /r "luts\*.*"

  ; --- Copy styles ---
  SetOutPath "${APP_PATH}\styles"
  File /r "styles\*.*"

  ; --- Copy runtime (Python + FFmpeg) ---
  SetOutPath "${APP_PATH}\runtime"
  File /r "runtime\*.*"

  ; --- Copy launcher script ---
  SetOutPath "${APP_PATH}\scripts"
  File "scripts\Start-FlagshipEditor-Backend.cmd"

  ; --- Write registry entries ---
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

  ; --- Create uninstaller ---
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; --- Create Start Menu shortcuts ---
  CreateDirectory "$SMPROGRAMS\ake-studio"
  CreateShortcut "$SMPROGRAMS\ake-studio\FlagshipEditor.lnk" "${APP_PATH}\scripts\Start-FlagshipEditor-Backend.cmd" "" "" "" SW_SHOWMINIMIZED "" "Start FlagshipEditor Backend"
  CreateShortcut "$SMPROGRAMS\ake-studio\Uninstall FlagshipEditor.lnk" "$INSTDIR\uninstall.exe" "" "" "" SW_SHOWNORMAL "" "Uninstall FlagshipEditor"

  ; --- Write payload checksums for verification ---
  SetOutPath "$INSTDIR"
  File "payload-checksums.json"

  DetailPrint "FlagshipEditor ${APP_VERSION} installed successfully."
  DetailPrint "CEP Extension: ${CEP_PATH}"
  DetailPrint "Runtime: ${APP_PATH}"
  DetailPrint ""
  DetailPrint "Open After Effects > Window > Extensions > FlagshipEditor"
SectionEnd

; ============================================================
; Uninstall Section
; ============================================================

Section "Uninstall"
  ; --- Stop backend if running ---
  nsExec::ExecToLog 'taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq FlagshipEditor*"'
  Sleep 1000

  ; --- Remove CEP extension ---
  RMDir /r /REBOOTOK "${CEP_PATH}"

  ; --- Remove runtime and engine ---
  RMDir /r /REBOOTOK "${APP_PATH}"
  RMDir /r /REBOOTOK "$LOCALAPPDATA\ake-studio\FlagshipEditor"

  ; --- Remove registry entries ---
  DeleteRegKey HKCU "Software\ake-studio\FlagshipEditor"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlagshipEditor"

  ; --- Remove Start Menu shortcuts ---
  Delete "$SMPROGRAMS\ake-studio\FlagshipEditor.lnk"
  Delete "$SMPROGRAMS\ake-studio\Uninstall FlagshipEditor.lnk"
  RMDir "$SMPROGRAMS\ake-studio"

  ; --- Remove uninstaller ---
  Delete "$INSTDIR\uninstall.exe"
  Delete "$INSTDIR\installed-version.txt"
  Delete "$INSTDIR\payload-checksums.json"
  RMDir "$INSTDIR"

  DetailPrint "FlagshipEditor has been uninstalled."
SectionEnd