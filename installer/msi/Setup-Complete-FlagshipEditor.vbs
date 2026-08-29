' FlagshipEditor 3.1.0 - post-install confirmation and finishing pass.
'
' wixl cannot author MSI dialogs, so the package installs with the Windows
' Installer native progress UI. This script is the success page. It runs from
' InstallUISequence after ExecuteAction (interactive installs only, as the
' invoking user, not elevated) and it must never block or fail the install -
' its custom action ignores the exit code, and every step in here is
' best-effort. It:
'
'   1. writes PlayerDebugMode into the *invoking* user's HKCU (the elevated
'      server side already writes it, but elevation may run as a different
'      account than the one that will use After Effects);
'   2. WAITS until the elevated install has actually committed the payload.
'      This script is file 1 of 5831 in the package while pythonw.exe is file
'      5804, and on a real Windows 11 host this script was observed running
'      while the runtime tree was still being copied - the second field
'      failure of the 3.0.0 MSI was its own backend launcher declaring the
'      half-copied install "incomplete". No sequencing assumption replaces
'      this wait: readiness means the sentinel files exist, the installer's
'      HKLM version stamp (written at the end of the transaction) matches,
'      and the biggest sentinel has stopped growing;
'   3. removes a leftover per-user ZIP installation of this same product, so
'      After Effects never sees two FlagshipEditor panels fighting over one
'      backend port;
'   4. detects After Effects 2024+ by enumerating every installed version -
'      never by testing a fixed list of registry keys, which is exactly the
'      false negative that broke the first published 3.0.0 MSI;
'   5. starts the backend windowlessly and confirms the result clearly.
Option Explicit

Const HEALTH_URL = "http://127.0.0.1:18791/health"
Const SHUTDOWN_URL = "http://127.0.0.1:18791/shutdown"
Const HKLM = &H80000002
Const AE_KEY = "SOFTWARE\Adobe\After Effects"
Const EXTENSION_ID = "com.akestudio.flagshipeditor"

Dim shell, fso, baseDir, startVbs, generation, waited
Dim aeBestMajor, legacyRemoved, message, icon

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
startVbs = baseDir & "\Start-FlagshipEditor-Backend.vbs"

' ── 1. CEP debug mode for the real user ─────────────────────────────
On Error Resume Next
For generation = 9 To 13
  shell.RegWrite "HKCU\Software\Adobe\CSXS." & generation & "\PlayerDebugMode", "1", "REG_SZ"
Next
On Error GoTo 0

' ── 2. Wait for the install transaction to finish writing ───────────
If Not WaitForCommittedPayload() Then
  MsgBox "FlagshipEditor 3.1.0 has not finished installing its files yet." & vbCrLf & vbCrLf & _
         "Still missing: " & FirstMissingPiece() & vbCrLf & vbCrLf & _
         "Wait for the installer window to finish. If it finishes without an error, " & _
         "start the backend from the Start Menu (Start FlagshipEditor Backend) or just open the panel in After Effects." & vbCrLf & _
         "If the installer window reported an error, the installation was rolled back - run the installer again. " & _
         "No uninstall is needed first.", _
         vbExclamation, "FlagshipEditor 3.1.0"
  WScript.Quit 0
End If

' ── 3. Retire a per-user ZIP installation of this product ───────────
legacyRemoved = RemoveLegacyZipInstall()

' ── 4. Detect After Effects 2024+ ───────────────────────────────────
aeBestMajor = NewestAfterEffectsMajor()

' ── 5. Start the backend and confirm ────────────────────────────────
If fso.FileExists(startVbs) Then
  On Error Resume Next
  shell.Run "wscript.exe //nologo """ & startVbs & """", 0, True
  On Error GoTo 0
End If

' The first backend start imports NumPy, librosa and OpenCV, which can take a
' while on a cold machine; a bounded wait keeps the confirmation honest
' without stalling the installer.
waited = 0
Do While waited < 20 And Not BackendIsHealthy()
  WScript.Sleep 1000
  waited = waited + 1
Loop

If aeBestMajor >= 24 Then
  icon = vbInformation
  message = "FlagshipEditor 3.1.0 is installed for After Effects " & AeYear(aeBestMajor) & "."
ElseIf aeBestMajor > 0 Then
  icon = vbExclamation
  message = "FlagshipEditor 3.1.0 is installed, but the newest Adobe After Effects on this computer (version " & _
            aeBestMajor & ") is older than After Effects 2024." & vbCrLf & _
            "Update After Effects to 2024 or newer and the panel will appear."
Else
  icon = vbExclamation
  message = "FlagshipEditor 3.1.0 is installed, but Adobe After Effects was not detected on this computer." & vbCrLf & _
            "Install After Effects 2024 or newer from Creative Cloud and the panel will appear."
End If

If BackendIsHealthy() Then
  message = message & vbCrLf & vbCrLf & "The analysis backend is running."
Else
  message = message & vbCrLf & vbCrLf & "The analysis backend is still starting and will finish in the background."
End If

If legacyRemoved Then
  message = message & vbCrLf & vbCrLf & "A previous ZIP-based installation was removed to avoid duplicate panels."
End If

MsgBox message & vbCrLf & vbCrLf & _
       "Open After Effects, then Window > Extensions > FlagshipEditor.", _
       icon, "FlagshipEditor 3.1.0"

WScript.Quit 0

' ─────────────────────────────────────────────────────────────────────
Function PayloadReady()
  ' The sentinels span the payload: the two backend entry points, the last
  ' big runtime binaries, and the HKLM stamp WriteRegistryValues emits near
  ' the very end of the install transaction.
  Dim stamp
  PayloadReady = False
  If Not fso.FileExists(baseDir & "\engine\backend_launcher.py") Then Exit Function
  If Not fso.FileExists(baseDir & "\engine\server.py") Then Exit Function
  If Not fso.FileExists(baseDir & "\runtime\python\pythonw.exe") Then Exit Function
  If Not fso.FileExists(baseDir & "\runtime\bin\ffprobe.exe") Then Exit Function
  stamp = ""
  On Error Resume Next
  stamp = shell.RegRead("HKLM\SOFTWARE\ake-studio\FlagshipEditor\Version")
  Err.Clear
  On Error GoTo 0
  If stamp <> "3.1.0" Then Exit Function
  PayloadReady = True
End Function

Function FirstMissingPiece()
  Dim piece
  For Each piece In Array("\engine\backend_launcher.py", "\engine\server.py", _
                          "\runtime\python\pythonw.exe", "\runtime\bin\ffprobe.exe")
    If Not fso.FileExists(baseDir & piece) Then
      FirstMissingPiece = baseDir & piece
      Exit Function
    End If
  Next
  FirstMissingPiece = "the installer's registry version stamp"
End Function

Function WaitForCommittedPayload()
  ' Poll for up to 5 minutes, then require pythonw.exe to hold a stable size
  ' across two seconds so a file mid-copy is never treated as done.
  Dim waitedSeconds, sizeBefore, sizeAfter
  WaitForCommittedPayload = False
  waitedSeconds = 0
  Do While waitedSeconds <= 300
    If PayloadReady() Then
      On Error Resume Next
      sizeBefore = -1
      sizeAfter = -2
      sizeBefore = fso.GetFile(baseDir & "\runtime\python\pythonw.exe").Size
      WScript.Sleep 2000
      sizeAfter = fso.GetFile(baseDir & "\runtime\python\pythonw.exe").Size
      Err.Clear
      On Error GoTo 0
      If sizeBefore = sizeAfter And sizeBefore > 0 Then
        WaitForCommittedPayload = True
        Exit Function
      End If
    Else
      WScript.Sleep 2000
    End If
    waitedSeconds = waitedSeconds + 2
  Loop
End Function

Function AeYear(major)
  ' Adobe's version-to-year mapping since the 2022 renumbering: 22.x = 2022.
  AeYear = "20" & major
End Function

Function NewestAfterEffectsMajor()
  ' Every installed AE release registers HKLM\SOFTWARE\Adobe\After Effects\
  ' <major.minor>. Enumerate them all so no update can produce a false
  ' negative, then fall back to the default install folders.
  Dim reg, subkeys, key, major, year
  NewestAfterEffectsMajor = 0
  On Error Resume Next
  Set reg = GetObject("winmgmts:{impersonationLevel=impersonate}!\\.\root\default:StdRegProv")
  If Err.Number = 0 Then
    reg.EnumKey HKLM, AE_KEY, subkeys
    If Err.Number = 0 And IsArray(subkeys) Then
      For Each key In subkeys
        major = MajorOf(key)
        If major > NewestAfterEffectsMajor Then NewestAfterEffectsMajor = major
      Next
    End If
  End If
  Err.Clear
  On Error GoTo 0
  If NewestAfterEffectsMajor >= 24 Then Exit Function
  For year = 2024 To 2030
    If fso.FileExists(shell.ExpandEnvironmentStrings("%ProgramFiles%") & _
        "\Adobe\Adobe After Effects " & year & "\Support Files\AfterFX.exe") Then
      major = year - 2000
      If major > NewestAfterEffectsMajor Then NewestAfterEffectsMajor = major
    End If
  Next
End Function

Function MajorOf(versionKey)
  Dim head
  MajorOf = 0
  head = versionKey
  If InStr(head, ".") > 0 Then head = Left(head, InStr(head, ".") - 1)
  If IsNumeric(head) Then MajorOf = CLng(head)
End Function

Function RemoveLegacyZipInstall()
  ' The ZIP fallback installs per user: the panel under %APPDATA%\Adobe\CEP\
  ' extensions, the runtime under %LOCALAPPDATA%\ake-studio\FlagshipEditor\
  ' <version> and an HKCU Run autostart. All three belong to this product, so
  ' replacing them here is the same upgrade the ZIP installer itself performs.
  ' Everything is signature-checked before deletion and best-effort.
  Dim userCep, manifestFile, manifest, runValue, dataRoot, folder, childFolder
  Dim legacyPaths(), legacyCount, index, removed, attempt
  RemoveLegacyZipInstall = False
  removed = False
  On Error Resume Next

  userCep = shell.ExpandEnvironmentStrings("%APPDATA%") & "\Adobe\CEP\extensions\" & EXTENSION_ID
  If fso.FolderExists(userCep) And fso.FileExists(userCep & "\CSXS\manifest.xml") Then
    Set manifestFile = fso.OpenTextFile(userCep & "\CSXS\manifest.xml", 1)
    manifest = manifestFile.ReadAll()
    manifestFile.Close
    If InStr(manifest, EXTENSION_ID) > 0 Then
      RequestBackendShutdown
      fso.DeleteFolder userCep, True
      If Not fso.FolderExists(userCep) Then removed = True
    End If
  End If

  runValue = ""
  runValue = shell.RegRead("HKCU\Software\Microsoft\Windows\CurrentVersion\Run\FlagshipEditorBackend")
  If InStr(runValue, "\ake-studio\FlagshipEditor\") > 0 Then
    shell.RegDelete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run\FlagshipEditorBackend"
    removed = True
  End If

  dataRoot = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\ake-studio\FlagshipEditor"
  If fso.FolderExists(dataRoot) Then
    ' Collect first, delete after: removing folders while walking the live
    ' SubFolders collection is undefined behaviour in FSO.
    Set folder = fso.GetFolder(dataRoot)
    ReDim legacyPaths(folder.SubFolders.Count)
    legacyCount = 0
    For Each childFolder In folder.SubFolders
      ' Only a ZIP runtime tree carries both signatures; the MSI backend keeps
      ' nothing but cache/, logs/ and backend.pid in this per-user directory.
      If fso.FileExists(childFolder.Path & "\engine\server.py") And _
         fso.FileExists(childFolder.Path & "\runtime\python\pythonw.exe") Then
        legacyPaths(legacyCount) = childFolder.Path
        legacyCount = legacyCount + 1
      End If
    Next
    For index = 0 To legacyCount - 1
      RequestBackendShutdown
      For attempt = 1 To 3
        fso.DeleteFolder legacyPaths(index), True
        If Not fso.FolderExists(legacyPaths(index)) Then Exit For
        WScript.Sleep 1000
      Next
      If Not fso.FolderExists(legacyPaths(index)) Then removed = True
    Next
  End If

  Err.Clear
  On Error GoTo 0
  RemoveLegacyZipInstall = removed
End Function

Sub RequestBackendShutdown()
  ' On a fresh install nothing of ours is running yet unless a ZIP backend
  ' owns the port, so a blind best-effort shutdown is safe here.
  Dim http
  On Error Resume Next
  Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  If Err.Number = 0 Then
    http.setTimeouts 1000, 1000, 2000, 3000
    http.open "POST", SHUTDOWN_URL, False
    http.send ""
    If Err.Number = 0 Then WScript.Sleep 2000
  End If
  Err.Clear
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
