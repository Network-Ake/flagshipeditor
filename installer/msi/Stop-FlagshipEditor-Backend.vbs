' FlagshipEditor 3.1.0 - stop the local analysis backend.
'
' /shutdown is the clean path: the backend flushes its response, removes its PID
' file and exits. The PID file is the fallback for a wedged process.
Option Explicit

Const SHUTDOWN_URL = "http://127.0.0.1:18791/shutdown"

Dim shell, fso, dataDir, pidFile, http, pid

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

dataDir = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\ake-studio\FlagshipEditor"
pidFile = dataDir & "\backend.pid"

On Error Resume Next
Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
If Err.Number = 0 Then
  http.setTimeouts 1000, 1000, 3000, 5000
  http.open "POST", SHUTDOWN_URL, False
  http.send ""
  If Err.Number = 0 And http.status = 200 Then
    On Error GoTo 0
    WScript.Quit 0
  End If
End If
Err.Clear
On Error GoTo 0

If Not fso.FileExists(pidFile) Then WScript.Quit 0

pid = Trim(fso.OpenTextFile(pidFile, 1).ReadAll())
If Len(pid) > 0 And IsNumeric(pid) Then
  shell.Run "taskkill.exe /PID " & CLng(pid) & " /T /F", 0, True
End If

On Error Resume Next
fso.DeleteFile pidFile, True
On Error GoTo 0
