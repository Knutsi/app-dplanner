@echo off
rem The last step of the unattended install: hand over to provision.ps1 and get out of the way.
rem
rem Nothing is decided here. This file runs exactly once per disk, in a context with no console
rem to watch and no way to re-run without reinstalling Windows, so all it does is copy the
rem payload out of C:\OEM (a copy, not a mount — the host cannot read it) into C:\work, where
rem the harness can reach it, and call the script that does the work. Everything that can go
rem wrong lives in provision.ps1, which `windows_check.py provision` re-runs as often as needed.
rem
rem It always exits 0. A non-zero exit can wedge dockur's setup with no Windows to log into,
rem and the harness reports what is missing far better than a failed install ever could.

if not exist C:\work mkdir C:\work
copy /y C:\OEM\provision.ps1   C:\work\provision.ps1   >nul 2>&1
copy /y C:\OEM\authorized_keys C:\work\authorized_keys >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -File C:\work\provision.ps1 ^
    -AuthorizedKey C:\work\authorized_keys -UserName dplanner -WithSsh >> C:\work\provision.log 2>&1

rem Best effort, so the host can read the log even if sshd never came up. \\host.lan\Data is
rem the /shared bind; Z: is mapped only for an interactive logon, which this may not be.
copy /y C:\work\provision.log \\host.lan\Data\provision.log >nul 2>&1
copy /y C:\work\provision.log Z:\provision.log             >nul 2>&1
exit /b 0
