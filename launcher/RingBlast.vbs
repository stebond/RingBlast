' RingBlast silent launcher: starts the program without any console window.
' On the first run (no private environment yet) the setup window of RingBlast.bat is shown instead.
Dim sh, fso, root
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
sh.CurrentDirectory = root
If fso.FileExists(root & "\.venv\Scripts\pythonw.exe") Then
    sh.Run """" & root & "\.venv\Scripts\pythonw.exe"" -m ringblast.gui.launch", 0, False
Else
    sh.Run """" & root & "\RingBlast.bat""", 1, False
End If
