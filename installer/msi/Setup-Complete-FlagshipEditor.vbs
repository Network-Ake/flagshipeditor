' FlagshipEditor 3.0.0 - post-install confirmation.
'
' wixl cannot author MSI dialogs, so the package installs with the Windows
' Installer native progress UI. This script is the success page: it runs from
' InstallUISequence after a successful ExecuteAction (interactive installs
' only, as the invoking user, not elevated), starts the backend windowlessly
' and tells the user the install worked and what to do next.
Option Explicit

Const HEALTH_URL = "http://127.0.0.1:18791/health"

Dim shell, fso, baseDir, startVbs, waited, message

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
startVbs = baseDir & "\Start-FlagshipEditor-Backend.vbs"

If fso.FileExists(startVbs) Then
  shell.Run "wscript.exe //nologo """ & startVbs & """", 0, True
End If

' The first backend start imports NumPy, librosa and OpenCV, which can take a
' while on a cold machine; a bounded wait keeps the confirmation honest
' without stalling the installer.
waited = 0
Do While waited < 20 And Not BackendIsHealthy()
  WScript.Sleep 1000
  waited = waited + 1
Loop

If BackendIsHealthy() Then
  message = "FlagshipEditor 3.0.0 is installed and its analysis backend is running."
Else
  message = "FlagshipEditor 3.0.0 is installed. The analysis backend is still starting and will finish in the background."
End If

MsgBox message & vbCrLf & vbCrLf & _
       "Open After Effects, then Window > Extensions > FlagshipEditor.", _
       vbInformation, "FlagshipEditor 3.0.0"

WScript.Quit 0

Function BackendIsHealthy()
  Dim http
  BackendIsHealthy = False
  On Error Resume Next
  Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  If Err.Number <> 0 Then Exit Function
  http.setTimeouts 1000, 1000, 2000, 2000
  http.open "GET", HEALTH_URL, False
  http.send
  If Err.Number = 0 Then
    If http.status = 200 Then BackendIsHealthy = True
  End If
  On Error GoTo 0
End Function
