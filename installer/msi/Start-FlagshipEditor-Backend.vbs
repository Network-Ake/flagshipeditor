' FlagshipEditor 3.1.0 - windowless backend launcher.
'
' The Start Menu shortcut and the CEP panel both come through here. Running the
' backend under wscript keeps every window off the screen: pythonw.exe has no
' console of its own and Run's window style 0 hides the host script as well.
Option Explicit

Const HEALTH_URL = "http://127.0.0.1:18791/health"

Dim shell, fso, baseDir, dataDir, cacheDir, pythonw, launcher, env, waited

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
dataDir = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\ake-studio\FlagshipEditor"
cacheDir = dataDir & "\cache"

pythonw = baseDir & "\runtime\python\pythonw.exe"
launcher = baseDir & "\engine\backend_launcher.py"

' This script lands on disk as one of the first files of the MSI payload,
' several thousand files before pythonw.exe, so the Start Menu shortcut (or
' anything else) can invoke it while an install or repair is still copying
' the runtime. A short bounded wait beats declaring a healthy install broken;
' the field failure of the first 3.0.0 MSI was exactly this message firing
' mid-copy.
waited = 0
Do While waited < 15 And Not RuntimePresent()
  WScript.Sleep 1000
  waited = waited + 1
Loop

If Not RuntimePresent() Then
  MsgBox "The FlagshipEditor runtime is incomplete in:" & vbCrLf & vbCrLf & _
         baseDir & vbCrLf & vbCrLf & _
         "If an installation or repair is still running, wait for it to finish, " & _
         "then use the Start Menu shortcut again." & vbCrLf & _
         "Otherwise run the FlagshipEditor 3.1.0 installer again to repair it.", _
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

Function RuntimePresent()
  RuntimePresent = fso.FileExists(pythonw) And fso.FileExists(launcher)
End Function

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
