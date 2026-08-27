' FlagshipEditor 3.0.0 - windowless backend launcher.
'
' The Start Menu shortcut and the CEP panel both come through here. Running the
' backend under wscript keeps every window off the screen: pythonw.exe has no
' console of its own and Run's window style 0 hides the host script as well.
Option Explicit

Const HEALTH_URL = "http://127.0.0.1:18791/health"

Dim shell, fso, baseDir, dataDir, cacheDir, pythonw, launcher, env

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
dataDir = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\ake-studio\FlagshipEditor"
cacheDir = dataDir & "\cache"

pythonw = baseDir & "\runtime\python\pythonw.exe"
launcher = baseDir & "\engine\backend_launcher.py"

If Not fso.FileExists(pythonw) Or Not fso.FileExists(launcher) Then
  MsgBox "The FlagshipEditor runtime is incomplete in:" & vbCrLf & vbCrLf & _
         baseDir & vbCrLf & vbCrLf & _
         "Reinstall FlagshipEditor 3.0.0 to repair it.", _
         vbExclamation, "FlagshipEditor"
  WScript.Quit 60
End If

' Already answering? Then this is a second click on the shortcut, not a restart.
If BackendIsHealthy() Then WScript.Quit 0

EnsureFolder dataDir
EnsureFolder cacheDir
EnsureFolder dataDir & "\logs"

' Child processes inherit this process' environment, so the engine finds the
' bundled FFmpeg and writes its caches somewhere a standard user can write.
Set env = shell.Environment("PROCESS")
env("PATH") = baseDir & "\runtime\bin;" & env("PATH")
env("FLAGSHIPEDITOR_FFMPEG") = baseDir & "\runtime\bin\ffmpeg.exe"
env("FLAGSHIPEDITOR_FFPROBE") = baseDir & "\runtime\bin\ffprobe.exe"
env("FLAGSHIPEDITOR_ENGINE") = baseDir & "\engine"
env("FLAGSHIPEDITOR_DATA") = dataDir
env("FLAGSHIPEDITOR_CACHE") = cacheDir
env("FLAGSHIPEDITOR_THUMBNAILS") = cacheDir & "\thumbnails"

' The install directory is read-only for a standard user, so the backend runs
' with the writable data directory as its working directory.
shell.CurrentDirectory = dataDir
shell.Run """" & pythonw & """ """ & launcher & """", 0, False

WScript.Quit 0

Sub EnsureFolder(path)
  Dim parent
  If fso.FolderExists(path) Then Exit Sub
  parent = fso.GetParentFolderName(path)
  If Len(parent) > 0 Then EnsureFolder parent
  On Error Resume Next
  fso.CreateFolder path
  On Error GoTo 0
End Sub

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
