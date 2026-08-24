OutFile "test-zip-installer.exe"
InstallDir "$LOCALAPPDATA\FlagshipEditorTest"
Section
  SetOutPath "$INSTDIR"
  File "..\flagshipeditor.zip"
SectionEnd
