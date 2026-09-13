<#
  The way in to a Windows VM that has no SSH: a loop in the guest watching the host's shared
  folder for jobs.

      powershell -NoProfile -ExecutionPolicy Bypass -File Z:\dplanner\runner.ps1

  Omarchy's Windows VM (`omarchy-windows-vm`) publishes only 8006 and 3389, and adding a port
  means recreating a container that belongs to the developer, not to this check. It does bind a
  shared folder, and that is enough: the host drops <id>.ps1 into inbox\, this runs it, and the
  output and exit code come back in outbox\. No new ports, nothing privileged, and the
  developer's own VM is left exactly as it was.

  It is also why the interactive half works at all. A process started over Windows OpenSSH
  lands in the SSH logon session, so a window it opens paints to a desktop nobody is looking at
  and a screen capture comes back black. This loop is started *by the logged-in user on the
  desktop*, so everything it runs is already in the interactive session: `dpw` really appears,
  and CopyFromScreen really returns pixels.

  Stop it with Ctrl+C, or by dropping a file called `stop` into inbox\.
#>
param(
    [string]$Root = "",
    [int]$PollMs  = 500
)

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'
# This repository's test names carry —, ▸ and ’. Python on Windows still writes a pipe in the
# ANSI code page, so without UTF-8 the run dies in UnicodeEncodeError somewhere in pytest's
# reporter and the real result is never seen.
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# Short, because pytest's tmp_path plus this repository's test names passes 260 characters.
$env:TEMP = 'C:\t'; $env:TMP = 'C:\t'

# Where the host's shared folder turns up depends on how the container was built: dockur
# maps it as drive Z: for an interactive logon and serves the same folder over SMB at
# \\host.lan\Data. Try both rather than make the developer find out which by having the
# first run fail.
if (-not $Root) {
    foreach ($candidate in @('Z:\', '\\host.lan\Data\', '\\host.lan\Shared\')) {
        if (Test-Path $candidate) { $Root = Join-Path $candidate 'dplanner'; break }
    }
}
if (-not $Root) {
    Write-Host 'No shared folder found. Looked for Z:\, \\host.lan\Data and \\host.lan\Shared.'
    Write-Host 'Pass one explicitly:  runner.ps1 -Root <path>\dplanner'
    exit 1
}

$inbox  = Join-Path $Root 'inbox'
$outbox = Join-Path $Root 'outbox'
foreach ($d in @($Root, $inbox, $outbox, 'C:\t')) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

Write-Host "dplanner runner: watching $inbox"
Write-Host "  (this window is the interactive desktop session — leave it open)"

while ($true) {
    # A heartbeat, so `windows_check.py status` can tell "the runner is not running" from
    # "the job is slow" — two very different things to be waiting on.
    try {
        @{ at = (Get-Date -Format o); pid = $PID; user = $env:USERNAME } |
            ConvertTo-Json | Set-Content (Join-Path $Root 'runner.json') -Encoding ascii
    } catch { }

    if (Test-Path (Join-Path $inbox 'stop')) {
        Remove-Item (Join-Path $inbox 'stop') -Force -ErrorAction SilentlyContinue
        Write-Host 'stop requested'
        break
    }

    $job = Get-ChildItem -Path $inbox -Filter '*.ps1' -ErrorAction SilentlyContinue |
           Sort-Object Name | Select-Object -First 1
    if (-not $job) { Start-Sleep -Milliseconds $PollMs; continue }

    $id  = [IO.Path]::GetFileNameWithoutExtension($job.Name)
    $log = Join-Path $outbox "$id.log"
    $done= Join-Path $outbox "$id.done"
    # Claimed by moving it out of the inbox first: a half-written job file the host is still
    # copying must not be picked up, and a job must never run twice.
    $mine = Join-Path $outbox "$id.ps1"
    try { Move-Item $job.FullName $mine -Force } catch { Start-Sleep -Milliseconds $PollMs; continue }

    Write-Host "--> $id"
    Remove-Item $done -Force -ErrorAction SilentlyContinue
    $started = Get-Date
    try {
        # A child process rather than dot-sourcing, so a job that wedges or calls exit cannot
        # take the runner down with it — the loop has to outlive every job it runs.
        & powershell -NoProfile -ExecutionPolicy Bypass -File $mine *>&1 |
            Tee-Object -FilePath $log
        $code = $LASTEXITCODE
    } catch {
        $_.Exception.Message | Out-File -FilePath $log -Append -Encoding utf8
        $code = 1
    }
    if ($null -eq $code) { $code = 0 }
    $secs = [int]((Get-Date) - $started).TotalSeconds
    # The exit file is written last and read as the signal that the log is complete.
    @{ code = $code; seconds = $secs; at = (Get-Date -Format o) } |
        ConvertTo-Json | Set-Content $done -Encoding ascii
    Write-Host "<-- $id exit $code in ${secs}s"
}
