<#
  Everything the Windows target needs to answer a check: git, uv, a Python, an identity to
  commit with, C:\work, and -- for the throwaway box -- sshd with a key.

  Two callers, which is the whole point of this file existing separately from install.bat:
  C:\OEM\install.bat runs it once at the end of the unattended install, and
  `windows_check.py provision` runs it again whenever it changes. install.bat runs exactly
  once per disk, in a context with no console to watch and no way to retry without
  reinstalling Windows; this file can be run as many times as it takes. So every step tests
  before it acts, nothing throws, and a step that fails is logged while the next one runs --
  because the one thing that must survive a bad run is the way back in.
#>
# ASCII only, on purpose. install.bat calls `powershell`, which is Windows PowerShell 5.1,
# and 5.1 reads a .ps1 with no byte-order mark as ANSI rather than UTF-8. An em dash in a
# double-quoted string then ends the string early, and the whole file fails to parse with an
# error pointing thirty lines away from the character that caused it. That is how the first
# provisioning run of this box failed. Keep the prose plain here; a BOM would also work and
# is one silent byte for an editor to lose.
param(
    [string]$AuthorizedKey = "",          # empty = no sshd; the Omarchy VM is driven over its share
    [string]$UserName      = "knut",
    [switch]$WithSsh
)

$ErrorActionPreference = 'Continue'
# Without this every Invoke-WebRequest paints a progress bar into a non-interactive host and
# runs about ten times slower -- the difference between a 40-second and a 7-minute provision.
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# windows_check.py compares this against C:\work\provisioned.json and re-provisions when they
# differ. Bump it whenever this file changes.
$PROVISION_VERSION = 3

# How long to let Windows Update have before falling back to the pinned GitHub build.
$CAPABILITY_TIMEOUT_S = 150

function Say($m) { Write-Output ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m) }
function Step($name, $block) {
    Say "=> $name"
    try { & $block; Say "   ok" } catch { Say ("   FAILED: " + $_.Exception.Message) }
}

Say "provision v$PROVISION_VERSION for $UserName (ssh: $WithSsh)"
Step 'directories' { New-Item -ItemType Directory -Force -Path C:\work, C:\work\logs, C:\tools, C:\t | Out-Null }

# -- what Windows itself has to be told ------------------------------------------------------
# pytest's tmp_path, plus this repository's long test names, plus a git repository inside one,
# goes past 260 characters. The failure reads as a baffling FileNotFoundError rather than as a
# path limit, so it is worth turning off before it is ever hit. C:\t is the short TEMP the
# harness points runs at for the same reason.
Step 'long paths' {
    Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' LongPathsEnabled 1 -Type DWord
}
# dockur's host share is unauthenticated guest SMB. Windows 11 blocks guest logons by default,
# and from build 24H2 it also *requires SMB signing* -- which a guest session cannot do, so
# the first switch alone is not enough there. Set-SmbClientConfiguration is the supported
# cmdlet and takes effect live. The first version of this step wrote the registry key and
# then Restart-Service'd LanmanWorkstation -Force: that wedged the redirector on two boots
# running, and \\host.lan\Data was gone for every session until a reboot. Never force-restart
# the workstation service on a machine you still need to reach.
# A network drive belongs to a logon session, so Z: exists only for the logged-in user; the
# UNC path is what a non-interactive run must use.
Step 'SMB guest access' {
    Set-SmbClientConfiguration -EnableInsecureGuestLogons $true -RequireSecuritySignature $false -Force
}

# -- git: the one real prerequisite ----------------------------------------------------------
# uv brings its own Python, so Python is not one. git is: core/storage/git.py shells out to it
# and the suite's fixtures call init_repo. Not winget -- it is an MSIX package that is not
# registered for SYSTEM and is missing or stale on a freshly installed image, and in that state
# `winget install` can fail with a source error and still exit 0.
Step 'git' {
    if (-not (Test-Path 'C:\Program Files\Git\cmd\git.exe')) {
        $rel = Invoke-RestMethod 'https://api.github.com/repos/git-for-windows/git/releases/latest' `
                                 -Headers @{ 'User-Agent' = 'dplanner' }
        $asset = $rel.assets | Where-Object { $_.name -like 'Git-*-64-bit.exe' } | Select-Object -First 1
        Say ("   " + $asset.name)
        Invoke-WebRequest $asset.browser_download_url -OutFile C:\work\git-setup.exe
        # /NORESTART matters: the Inno installer reboots mid-provision without it.
        Start-Process C:\work\git-setup.exe -Wait -ArgumentList `
            '/VERYSILENT','/NORESTART','/NOCANCEL','/SP-','/SUPPRESSMSGBOXES'
    }
}
# --system, not --global: install.bat may run as SYSTEM, whose --global is the system profile
# and reaches nobody. Without an identity every test that commits dies with "Please tell me who
# you are", because production code passes no -c user.name. autocrlf=false because the suite
# writes files and reads them back expecting its own bytes.
Step 'git identity' {
    $git = 'C:\Program Files\Git\cmd\git.exe'
    if (Test-Path $git) {
        & $git config --system user.name  'DPlanner Windows Check'
        & $git config --system user.email 'windows-check@dplanner.invalid'
        & $git config --system init.defaultBranch main
        & $git config --system core.autocrlf false
        & $git config --system core.longpaths true
        & $git config --system safe.directory '*'
    }
}

# -- uv --------------------------------------------------------------------------------------
# UV_INSTALL_DIR is not optional. The installer defaults to %USERPROFILE%\.local\bin, and under
# SYSTEM that is the system profile -- uv lands where no logon will ever see it and nothing says
# so. The python and cache directories are pinned machine-wide for the same reason.
Step 'uv' {
    if (-not (Test-Path 'C:\tools\uv\uv.exe')) {
        $env:UV_INSTALL_DIR = 'C:\tools\uv'; $env:UV_NO_MODIFY_PATH = '1'
        Invoke-Expression (Invoke-RestMethod 'https://astral.sh/uv/install.ps1')
    }
}
Step 'machine environment' {
    $k = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
    # The raw, unexpanded value. Reading PATH through $env: or Get-ItemProperty expands
    # %SystemRoot%, and writing that back bakes the expansion into every future logon -- the
    # classic way to wreck a machine PATH. Never setx /M either: it truncates at 1024 chars.
    $old = (Get-Item $k).GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    foreach ($p in 'C:\tools\uv', 'C:\Program Files\Git\cmd') {
        if ($old -notlike "*$p*") { $old = "$old;$p" }
    }
    Set-ItemProperty $k Path $old -Type ExpandString
    [Environment]::SetEnvironmentVariable('UV_PYTHON_INSTALL_DIR', 'C:\tools\uv\python', 'Machine')
    [Environment]::SetEnvironmentVariable('UV_CACHE_DIR',          'C:\tools\uv\cache',  'Machine')
}
Step 'python 3.13' {
    $env:UV_PYTHON_INSTALL_DIR = 'C:\tools\uv\python'; $env:UV_CACHE_DIR = 'C:\tools\uv\cache'
    & C:\tools\uv\uv.exe python install 3.13
}

# -- sshd, for the throwaway box only --------------------------------------------------------
if ($WithSsh) {
    # The capability is the cheap path and usually works. It fails with 0x800f0954 when Windows
    # Update is unreachable, and quietly -- Add-WindowsCapability returns a non-zero code rather
    # than throwing -- so the *service* is what gets tested, never the call.
    # Bounded on purpose. Add-WindowsCapability fetches from Windows Update, and on an image
    # that cannot reach it the call does not fail -- it hangs, which is worse, because the zip
    # below is the real fallback and it can only run if this one is allowed to give up. The
    # first boot of the throwaway box sat here for eight minutes and never came back.
    Step 'OpenSSH (capability)' {
        $cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
        if ($cap -and $cap.State -ne 'Installed') {
            $name = $cap.Name
            $job = Start-Job { Add-WindowsCapability -Online -Name $using:name | Out-Null }
            if (Wait-Job $job -Timeout $CAPABILITY_TIMEOUT_S) {
                Receive-Job $job | Out-Null
            } else {
                Say "   no answer in ${CAPABILITY_TIMEOUT_S}s -- giving up on Windows Update"
                Stop-Job $job
            }
            Remove-Job $job -Force -ErrorAction SilentlyContinue
        }
    }
    Step 'OpenSSH (zip fallback)' {
        if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
            Say '   capability produced no sshd; falling back to the Win32-OpenSSH release'
            $rel = Invoke-RestMethod 'https://api.github.com/repos/PowerShell/Win32-OpenSSH/releases/latest' `
                                     -Headers @{ 'User-Agent' = 'dplanner' }
            $url = ($rel.assets | Where-Object name -eq 'OpenSSH-Win64.zip').browser_download_url
            Invoke-WebRequest $url -OutFile C:\work\OpenSSH-Win64.zip
            Expand-Archive C:\work\OpenSSH-Win64.zip -DestinationPath C:\tools -Force
            & powershell -NoProfile -ExecutionPolicy Bypass -File 'C:\tools\OpenSSH-Win64\install-sshd.ps1'
        }
    }
    # 2222, not 22: qemu-docker's getUserPorts() silently drops any port under 1024 the
    # container process cannot bind, and an SSH that never answers looks exactly like a failed
    # install. USER_PORTS in the compose file forwards this one.
    Step 'sshd config' {
        $d = 'C:\ProgramData\ssh'; New-Item -ItemType Directory -Force -Path $d | Out-Null
        Start-Service sshd -ErrorAction SilentlyContinue
        Stop-Service  sshd -ErrorAction SilentlyContinue
        $c = Join-Path $d 'sshd_config'
        $t = if (Test-Path $c) { Get-Content $c -Raw } else { '' }
        $t = $t -replace '(?m)^#?\s*Port\s+\d+', 'Port 2222'
        if ($t -notmatch '(?m)^Port\s+2222') { $t = "Port 2222`r`n" + $t }
        # The stock config ends with a Match block sending every administrator to
        # administrators_authorized_keys, so a key in ~/.ssh/authorized_keys is read by nobody
        # and you get "Permission denied (publickey)" over a perfectly correct-looking file.
        $t = $t -replace '(?m)^(Match Group administrators)', '#$1'
        $t = $t -replace '(?m)^(\s+AuthorizedKeysFile.*administrators_authorized_keys)', '#$1'
        Set-Content -Path $c -Value $t -Encoding ascii
    }
    Step 'authorized key' {
        if ($AuthorizedKey -and (Test-Path $AuthorizedKey)) {
            $key = Get-Content $AuthorizedKey -Raw
            $dst = 'C:\ProgramData\ssh\administrators_authorized_keys'
            Set-Content -Path $dst -Value $key -Encoding ascii
            # The second half of the same trap: sshd refuses a key file any non-administrator
            # can write, and logs nothing the client ever sees. SIDs rather than names so a
            # non-English install still works.
            & icacls.exe $dst /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null
            $h = "C:\Users\$UserName\.ssh"
            New-Item -ItemType Directory -Force -Path $h | Out-Null
            Set-Content -Path (Join-Path $h 'authorized_keys') -Value $key -Encoding ascii
        } else { Say "   no key given -- password logon only" }
    }
    # DefaultShellCommandOption is not optional: OpenSSH appends cmd's /c by default,
    # powershell.exe rejects it, and every remote command then fails with a usage error that
    # looks nothing like the cause.
    Step 'default ssh shell' {
        New-Item -Path HKLM:\SOFTWARE\OpenSSH -Force | Out-Null
        Set-ItemProperty HKLM:\SOFTWARE\OpenSSH DefaultShell `
            'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
        Set-ItemProperty HKLM:\SOFTWARE\OpenSSH DefaultShellCommandOption '-Command'
    }
    Step 'firewall' {
        if (-not (Get-NetFirewallRule -Name 'dplanner-sshd' -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -Name dplanner-sshd -DisplayName 'OpenSSH (dplanner 2222)' `
                -Enabled True -Direction Inbound -Protocol TCP -Action Allow `
                -LocalPort 2222 -Profile Any | Out-Null
        }
    }
    # sshd reads the machine environment when the service starts, and everything above was put
    # on PATH after it started. Without this restart every session says "git is not recognized"
    # until somebody reboots, and it looks exactly like a failed install.
    Step 'restart sshd' {
        Set-Service sshd -StartupType Automatic
        Restart-Service sshd -Force -ErrorAction SilentlyContinue
        Start-Service sshd -ErrorAction SilentlyContinue
    }
}

@{ version = $PROVISION_VERSION
   at      = (Get-Date -Format o)
   user    = $UserName
   git     = (Test-Path 'C:\Program Files\Git\cmd\git.exe')
   uv      = (Test-Path 'C:\tools\uv\uv.exe')
   ssh     = [bool]$WithSsh
} | ConvertTo-Json | Set-Content C:\work\provisioned.json -Encoding ascii
Say 'provision done'
exit 0
