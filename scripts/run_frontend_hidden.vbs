' Launch the Vite dev server without a console window.
' ASCII-only on purpose: Windows Script Host reads .vbs files as ANSI.
Dim shell, here
Set shell = CreateObject("WScript.Shell")
here = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
shell.Run """" & here & "run_frontend.cmd""", 0, False
