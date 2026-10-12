Option Explicit
Dim shell, fso, root, script, candidate, candidates, i, launched, probe
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
script = root & "\bootstrap.py"
If Not fso.FileExists(script) Then
    MsgBox "Extract the entire AutoParts_Pro folder first. bootstrap.py is missing.", 16, "AutoParts Pro"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
candidates = Array("pyw -3.11", "pyw -3", "pythonw")
launched = False
On Error Resume Next
For i = 0 To UBound(candidates)
    Err.Clear
    probe = shell.Run(candidates(i) & " -c ""import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,15) and sys.maxsize > 2**32 else 1)""", 0, True)
    If Err.Number = 0 And probe = 0 Then
        shell.Run candidates(i) & " """ & script & """", 0, False
        If Err.Number = 0 Then
            launched = True
            Exit For
        End If
    End If
Next
On Error GoTo 0
If Not launched Then
    MsgBox "64-bit Python 3.11-3.14 is required. Install 64-bit Python from python.org with pip and Tcl/Tk enabled, then open AutoParts Pro.vbs again.", 16, "AutoParts Pro"
End If
