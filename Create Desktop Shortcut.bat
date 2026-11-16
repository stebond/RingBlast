@echo off
rem Creates the "RingBlast" shortcut (with its icon) on the Desktop and in the Start menu.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; foreach($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))){ $s=$w.CreateShortcut($d+'\RingBlast.lnk'); $s.TargetPath=$env:SystemRoot+'\System32\wscript.exe'; $s.Arguments='\"%~dp0launcher\RingBlast.vbs\"'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0launcher\ringblast.ico,0'; $s.Description='RingBlast - ring blast design'; $s.Save() }"
echo Shortcut "RingBlast" created on the Desktop and in the Start menu.
pause
