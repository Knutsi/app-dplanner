"""Run DPlanner's checks on Windows, in a VM this machine already has or one it brings up.

    uv run python scripts/windows_check.py status        # what the target has
    uv run python scripts/windows_check.py all           # sync, the three checks, build, shots
    uv run python scripts/windows_check.py clean         # give the disk back

The three checks, the PyInstaller build and a real window on a real desktop are the things
this repository cannot test on Linux, and none of them is worth a cloud runner: it is a rare,
manual check. Two targets, because the cheap one is usually already running:

``omarchy``  Omarchy's own Windows VM (``omarchy-windows-vm``), the default. It is installed,
             persistent and belongs to the developer, so nothing here recreates it, changes
             its ports or stops it. It publishes no SSH, but it binds a shared folder, and
             ``scripts/windows/runner.ps1`` turns that into a way in. Costs no extra disk, no
             extra RAM and no install.
``box``      A throwaway ``dockurr/windows`` container on ports nothing else uses, driven over
             SSH. Isolated and fully scriptable, at the price of a 20-30 minute first install.

Every verb stands alone, because the fix loop is *sync, run one check, read it, repeat* and
re-syncing or re-provisioning each time round is unusable:

    uv run python scripts/windows_check.py sync
    uv run python scripts/windows_check.py check pytest
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "scripts" / "windows"
STATE = Path(os.environ.get("DPLANNER_WIN_HOME", Path.home() / ".local/share/dplanner-windows"))
GUEST_TREE = r"C:\work\dplanner"

# What never goes to the guest. `.git` is correctness, not speed: in a worktree it is a *file*
# pointing at a path that does not exist over there, so find_repo_root would succeed and every
# git call after it fail. `.venv` holds Linux binaries the guest replaces with its own.
EXCLUDES = (
    ".git", ".venv", "__pycache__", "*.py[cod]", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", "dist", "build", "*.egg-info", "scripts/windows/storage",
)

# Prepended to every job. Set here rather than machine-wide: a developer's own Windows will not
# have these, and that is worth still testing on purpose.
PREAMBLE = r"""
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:TEMP = 'C:\t'; $env:TMP = 'C:\t'
$env:UV_PYTHON_INSTALL_DIR = 'C:\tools\uv\python'; $env:UV_CACHE_DIR = 'C:\tools\uv\cache'
$env:Path = 'C:\tools\uv;C:\Program Files\Git\cmd;' + $env:Path
"""


def say(message: str) -> None:
    print(message, flush=True)


# -- the two ways in ---------------------------------------------------------------------------


@dataclass
class Target:
    """Where the checks run, and how a job reaches it."""

    name: str
    share: Path       # the guest's shared folder, as this host sees it
    guest_share: str  # the same folder, as the guest sees it

    def run(self, script: str, label: str, *, quiet: bool = False) -> int:
        raise NotImplementedError

    def ready(self) -> str:
        """Empty when a job would run right now, otherwise why not."""
        raise NotImplementedError


class OmarchyTarget(Target):
    """Omarchy's VM, reached through the shared folder its container already binds.

    The host drops a job in ``inbox``; ``runner.ps1``, running on the desktop, picks it up and
    writes the output and the exit code back into ``outbox``. Crude, and it buys three things
    nothing else does: no new ports, no container recreation, and every job already inside the
    interactive session — so a window really opens and a screen capture really has pixels.
    """

    def _work(self) -> Path:
        return self.share / "dplanner"

    def ready(self) -> str:
        beat = self._work() / "runner.json"
        if not beat.is_file():
            return f"the runner is not running in the VM — {start_hint(self)}"
        age = time.time() - beat.stat().st_mtime
        if age > 30:
            return f"the runner last checked in {int(age)}s ago — {start_hint(self)}"
        return ""

    def run(self, script: str, label: str, *, quiet: bool = False) -> int:
        work = self._work()
        (work / "inbox").mkdir(parents=True, exist_ok=True)
        (work / "outbox").mkdir(parents=True, exist_ok=True)
        job = f"{int(time.time())}-{label}-{uuid.uuid4().hex[:6]}"
        # Written beside the inbox and moved in, so the runner cannot claim a half-written file.
        staged = work / "outbox" / f"{job}.staged"
        staged.write_text(PREAMBLE + script, encoding="utf-8")
        staged.rename(work / "inbox" / f"{job}.ps1")

        log, done = work / "outbox" / f"{job}.log", work / "outbox" / f"{job}.done"
        seen = 0
        while not done.is_file():
            seen = tail(log, seen, quiet=quiet)
            time.sleep(0.4)
        tail(log, seen, quiet=quiet)
        result = json.loads(done.read_text(encoding="utf-8", errors="replace") or "{}")
        keep_log(log, label)
        for leftover in (done, work / "outbox" / f"{job}.ps1", log):
            leftover.unlink(missing_ok=True)
        return int(result.get("code", 1))


class BoxTarget(Target):
    """The throwaway container, over SSH."""

    port = "2222"
    user = "dplanner"

    def _ssh(self) -> list[str]:
        keys = STATE / "oem" / "id_ed25519"
        return [
            "ssh", "-p", self.port, "-i", str(keys),
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            # A reinstall changes the host key; without its own file that means a confusing
            # failure and a manual ssh-keygen -R.
            "-o", f"UserKnownHostsFile={STATE / 'known_hosts'}",
            "-o", "ConnectTimeout=5",
            # A ten-minute build must not be dropped as idle.
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=40",
            "-o", "LogLevel=ERROR", f"{self.user}@127.0.0.1",
        ]

    def ready(self) -> str:
        probe = subprocess.run(
            [*self._ssh(), "exit 0"], capture_output=True, timeout=20, check=False
        )
        return "" if probe.returncode == 0 else "the box does not answer SSH — try `up` then `wait`"

    def run(self, script: str, label: str, *, quiet: bool = False) -> int:
        # -EncodedCommand, because ssh re-joins argv into one string and whatever shell is on
        # the far side gets a say in the quoting. Base64 removes the whole question.
        payload = base64.b64encode((PREAMBLE + script).encode("utf-16-le")).decode("ascii")
        argv = [*self._ssh(), "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-EncodedCommand", payload]
        return stream(argv, label, quiet=quiet)


def start_hint(target: Target) -> str:
    return (
        "start it in the VM (one line, in a PowerShell window on the desktop):\n"
        f"    powershell -NoProfile -ExecutionPolicy Bypass "
        f"-File {target.guest_share}\\dplanner\\runner.ps1\n"
        "  Open the VM with `omarchy-windows-vm launch`, or at http://localhost:8006"
    )


def omarchy_share() -> Path:
    return Path(f"/var/lib/omarchy/windows/mounts/users/{os.getuid()}/shared")


def target_for(name: str) -> Target:
    if name == "omarchy":
        return OmarchyTarget("omarchy", omarchy_share(), "Z:")
    return BoxTarget("box", STATE / "shared", r"\\host.lan\Data")


# -- running things ----------------------------------------------------------------------------


def logs_dir() -> Path:
    where = STATE / "logs"
    where.mkdir(parents=True, exist_ok=True)
    return where


def keep_log(log: Path, label: str) -> None:
    if log.is_file():
        shutil.copyfile(log, logs_dir() / f"{label}.log")


def tail(log: Path, seen: int, *, quiet: bool) -> int:
    """Print whatever has been appended since `seen`, and say how far we have read."""
    if not log.is_file():
        return seen
    size = log.stat().st_size
    if size <= seen:
        return seen
    with log.open("rb") as handle:
        handle.seek(seen)
        fresh = handle.read(size - seen)
    if not quiet:
        sys.stdout.write(fresh.decode("utf-8", "replace"))
        sys.stdout.flush()
    return size


def stream(argv: Sequence[str], label: str, *, quiet: bool = False) -> int:
    """Run, echo as it arrives, and tee to the step's own log."""
    log = logs_dir() / f"{label}.log"
    with log.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(
            list(argv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            sink.write(line)
            if not quiet:
                sys.stdout.write(line)
                sys.stdout.flush()
        return process.wait()


def docker(argv: Sequence[str]) -> list[str]:
    """A docker invocation, or a refusal that says exactly what is wrong.

    Only the box's `up`/`down` come here — every other verb is transport, not daemon — so a
    shell whose credentials predate the docker group can still run every check.
    """
    probe = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture_output=True, check=False, timeout=20,
    )
    if probe.returncode == 0:
        return ["docker", *argv]
    import grp

    try:
        group = grp.getgrnam("docker")
        stale = os.getuid() != 0 and group.gr_gid not in os.getgroups()
    except KeyError:
        stale = False
    hint = (
        "  Your account is in the docker group but this shell is not — its credentials\n"
        "  predate the change. Start a fresh login shell, or `exec newgrp docker`.\n"
        if stale else
        "  `sudo usermod -aG docker $USER`, then log out and back in.\n"
    )
    raise SystemExit(
        "docker: permission denied on /var/run/docker.sock\n" + hint
        + "  Only `up` and `down` on the --target box need docker. Everything else runs\n"
        "  against a VM that is already up — including the default --target omarchy."
    )


# -- the verbs ---------------------------------------------------------------------------------


def do_sync(target: Target) -> int:
    """Host tree into the share, then the share into a local disk in the guest."""
    staging = target.share / "dplanner" / "worktree"
    staging.mkdir(parents=True, exist_ok=True)
    argv = ["rsync", "-a", "--delete", *[f"--exclude={pattern}" for pattern in EXCLUDES],
            f"{REPO}/", f"{staging}/"]
    say(f"rsync -> {staging}")
    code = stream(argv, "sync-host", quiet=True)
    if code != 0:
        return code
    # A local disk, not the share: uv hardlinks out of its cache, and PyInstaller on a UNC path
    # produces some of the least legible errors in the ecosystem. /XD matters as much — /MIR
    # deletes anything not in the source, and the guest's own .venv is exactly that.
    return target.run(
        rf"""
robocopy {target.guest_share}\dplanner\worktree {GUEST_TREE} /MIR /NFL /NDL /NJH /NJS /R:1 /W:1 `
    /XD .venv .git __pycache__ .pytest_cache .ruff_cache .mypy_cache build dist
# robocopy's exit code is a bitmask: 0-7 all mean success, and only 8+ is a failure.
if ($LASTEXITCODE -lt 8) {{ Write-Host "sync ok ($LASTEXITCODE)"; exit 0 }}
else {{ exit $LASTEXITCODE }}
""",
        "sync",
    )


def bootstrap_line(target: Target, *, with_ssh: bool) -> str:
    """The one line to type into the guest when there is no way in yet.

    Provisioning is what *creates* the way in, so when it fails there is nothing to re-run it
    with — the box's first boot died on a parse error and left no sshd. This is the escape
    hatch: type it into the viewer once and the harness takes over from there.
    """
    user = BoxTarget.user if with_ssh else os.environ.get("USER", "knut")
    flag = " -WithSsh" if with_ssh else ""
    return (
        "powershell -NoProfile -ExecutionPolicy Bypass -File "
        rf"{target.guest_share}\dplanner\provision.ps1 -UserName {user}{flag}"
    )


def do_provision(target: Target, *, with_ssh: bool) -> int:
    payload = target.share / "dplanner"
    payload.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HARNESS / "provision.ps1", payload / "provision.ps1")
    shutil.copyfile(HARNESS / "runner.ps1", payload / "runner.ps1")
    user = BoxTarget.user if with_ssh else os.environ.get("USER", "knut")
    flag = "-WithSsh" if with_ssh else ""
    return target.run(
        rf"& {target.guest_share}\dplanner\provision.ps1 -UserName {user} {flag}", "provision"
    )


CHECKS = {
    "pytest": "uv run pytest -q",
    "ruff": "uv run ruff check",
    "mypy": "uv run mypy",
}


def do_check(target: Target, names: Sequence[str], extra: Sequence[str]) -> int:
    chosen = list(names) or list(CHECKS)
    worst = 0
    results = []
    for name in chosen:
        if name not in CHECKS:
            raise SystemExit(f"unknown check {name!r}; one of {', '.join(CHECKS)}")
        command = CHECKS[name] + ("".join(f" {word}" for word in extra) if len(chosen) == 1 else "")
        say(f"\n=== {name} ===")
        began = time.time()
        # Each on its own, so one red never hides the other two.
        code = target.run(f"Set-Location {GUEST_TREE}\n{command}\nexit $LASTEXITCODE", name)
        results.append((name, code, int(time.time() - began)))
        worst = worst or code
    say("")
    for name, code, seconds in results:
        say(f"  {'ok  ' if code == 0 else 'FAIL'}  {name:<8} {seconds}s")
    return worst


def do_build(target: Target) -> int:
    return target.run(
        rf"""
Set-Location {GUEST_TREE}
uv run --group build pyinstaller --noconfirm --clean dplanner.spec
if ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}
# A frozen app that cannot answer --help is not built, whatever PyInstaller said.
& dist\dplanner\dplanner.exe --help | Select-Object -First 3
if ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}
$size = (Get-ChildItem -Recurse dist | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("dist: {{0:N0}} MB" -f $size)
""",
        "build",
    )


def do_render(target: Target) -> int:
    scripts = sorted(path.name for path in (REPO / "scripts").glob("render_*.py"))
    body = "\n".join(
        f"Write-Host '--- {name} ---'; uv run python scripts/{name} "
        f"--out docs/screenshots/windows/{name[7:-3]}"
        for name in scripts
    )
    return target.run(f"Set-Location {GUEST_TREE}\n{body}", "render")


def do_window(target: Target, seconds: int) -> int:
    """Open the real window on the real desktop and photograph it.

    On the omarchy target the runner is already in the interactive session, so this is simply
    a job. On the box it would need schtasks /IT — a process started over SSH paints to a
    desktop nobody is looking at, and CopyFromScreen there returns black.
    """
    if target.name != "omarchy":
        say("note: --target box opens the window in the SSH session, where nothing can see it.")
        say("      Use --target omarchy for the interactive half, or watch RDP on 3390.")
    return target.run(
        rf"""
Set-Location {GUEST_TREE}
$env:QT_QPA_PLATFORM = ''          # a real window this time, not offscreen
$app = Start-Process -PassThru -FilePath (Resolve-Path .venv\Scripts\dpw.exe)
Start-Sleep -Seconds {seconds}
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$r = [Windows.Forms.SystemInformation]::VirtualScreen
$b = New-Object Drawing.Bitmap $r.Width, $r.Height
[Drawing.Graphics]::FromImage($b).CopyFromScreen($r.Location, [Drawing.Point]::Empty, $r.Size)
New-Item -ItemType Directory -Force -Path {target.guest_share}\dplanner\out | Out-Null
$b.Save('{target.guest_share}\dplanner\out\window.png', [Drawing.Imaging.ImageFormat]::Png)
Write-Host 'captured the desktop'
if (-not $app.HasExited) {{ Stop-Process -Id $app.Id -Force }}
""",
        "window",
    )


def do_collect(target: Target, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    code = target.run(
        rf"""
$dest = '{target.guest_share}\dplanner\out'
New-Item -ItemType Directory -Force -Path $dest | Out-Null
robocopy {GUEST_TREE}\docs\screenshots\windows $dest\screenshots /MIR /NFL /NDL /NJH /NJS /R:1 /W:1
if ($LASTEXITCODE -lt 8) {{ exit 0 }} else {{ exit $LASTEXITCODE }}
""",
        "collect",
    )
    landed = target.share / "dplanner" / "out"
    if landed.is_dir():
        shutil.copytree(landed, out, dirs_exist_ok=True)
        say(f"collected into {out}")
    return code


def do_clean(target: Target, *, everything: bool) -> int:
    """Give the disk back. Tools stay unless --all; the tree, the build and the caches go."""
    caches = "Remove-Item -Recurse -Force C:\\tools\\uv\\cache -EA SilentlyContinue"
    extra = caches if everything else ""
    code = target.run(
        rf"""
$gone = @('{GUEST_TREE}', 'C:\work\logs', 'C:\t', '{target.guest_share}\dplanner\worktree')
foreach ($p in $gone) {{
    if (Test-Path $p) {{
        Write-Host "removing $p"
        Remove-Item -Recurse -Force $p -EA SilentlyContinue
    }}
}}
{extra}
Write-Host 'guest cleaned'
""",
        "clean",
    )
    for path in (target.share / "dplanner" / "worktree", target.share / "dplanner" / "out"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            say(f"removed {path}")
    if everything:
        shutil.rmtree(logs_dir(), ignore_errors=True)
    return code


def disk_line(target: Target) -> None:
    target.run(
        r"""
$c = Get-PSDrive C
Write-Host ("guest C:  {0:N1} GB used, {1:N1} GB free" -f ($c.Used/1GB), ($c.Free/1GB))
foreach ($p in @('C:\work\dplanner', 'C:\tools', 'C:\work')) {
    if (Test-Path $p) {
        $f = Get-ChildItem -Recurse -Force $p -EA SilentlyContinue
        $n = ($f | Measure-Object Length -Sum).Sum
        Write-Host ("  {0,-22} {1:N0} MB" -f $p, ($n/1MB))
    }
}
""",
        "disk",
    )


def do_status(target: Target) -> int:
    say(f"target:      {target.name}")
    say(f"host share:  {target.share}{'' if target.share.is_dir() else '   (MISSING)'}")
    trouble = target.ready()
    say(f"reachable:   {'yes' if not trouble else 'no'}")
    if trouble:
        say(f"  {trouble}")
        return 1
    target.run(
        r"""
$p = 'C:\work\provisioned.json'
if (Test-Path $p) { Write-Host ("provisioned: " + (Get-Content $p -Raw).Trim().Replace("`n"," ")) }
else { Write-Host 'provisioned: no (run `provision`)' }
Write-Host ("git:         " + (& git --version 2>&1))
Write-Host ("uv:          " + (& uv --version 2>&1))
Get-CimInstance SoftwareLicensingProduct -Filter "PartialProductKey is not null" |
  ForEach-Object { Write-Host ("licence:     {0} status {1}" -f $_.Name, $_.LicenseStatus) }
""",
        "status",
    )
    disk_line(target)
    return 0


def do_up() -> int:
    """Bring the throwaway box up. The omarchy target is never started or stopped by this."""
    for name in ("oem", "shared", "storage", "logs"):
        (STATE / name).mkdir(parents=True, exist_ok=True)
    key = STATE / "oem" / "id_ed25519"
    if not key.is_file():
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "dplanner-windows", "-f", str(key)],
            check=True, capture_output=True,
        )
        say("generated a key for the box")
    shutil.copyfile(key.with_suffix(".pub"), STATE / "oem" / "authorized_keys")
    shutil.copyfile(HARNESS / "install.bat", STATE / "oem" / "install.bat")
    shutil.copyfile(HARNESS / "provision.ps1", STATE / "oem" / "provision.ps1")
    environment = {**os.environ, "DPLANNER_WIN_HOME": str(STATE)}
    argv = docker(["compose", "-f", str(HARNESS / "docker-compose.yml"), "up", "-d"])
    say("bringing the box up — the first boot installs Windows and takes 20-30 minutes")
    say("  watch it at http://localhost:8007")
    return subprocess.run(argv, env=environment, check=False).returncode


def do_wait(target: Target, timeout: int) -> int:
    began = time.time()
    while time.time() - began < timeout:
        trouble = target.ready()
        if not trouble:
            say(f"ready after {int(time.time() - began)}s")
            return 0
        waited = int(time.time() - began)
        if waited % 30 < 3:
            say(f"[{waited // 60:02d}:{waited % 60:02d}] {trouble.splitlines()[0]}")
        time.sleep(3)
    say(f"gave up after {timeout}s")
    return 1


# What `--destroy` removes, **named one by one**. dockur keeps the downloaded Windows ISO in
# /storage beside the disk it installed from it, and that download is 8 GB against a
# 25-minute install — so a reinstall should not need it again. An allow-list of what to keep
# was the first attempt and it deleted the ISO anyway: the safe direction for a rule that
# deletes is to name what goes, so anything unexpected survives instead of disappearing.
DISK_FILES = ("data.img", "setup.img", "windows.vars")


def do_down(target: Target, *, destroy: bool, yes: bool, forget_iso: bool = False) -> int:
    if target.name == "omarchy":
        raise SystemExit(
            "refusing: the omarchy target is the developer's own VM, not this check's.\n"
            "  Stop it yourself with `omarchy-windows-vm stop` if you mean to."
        )
    if destroy and not yes:
        raise SystemExit(
            "`down --destroy` deletes the Windows install; the next `up` reinstalls and takes\n"
            "20-30 minutes. Pass --yes if that is what you want."
        )
    environment = {**os.environ, "DPLANNER_WIN_HOME": str(STATE)}
    argv = docker(["compose", "-f", str(HARNESS / "docker-compose.yml"),
                   "down", *(["-v"] if destroy else [])])
    code = subprocess.run(argv, env=environment, check=False).returncode
    if destroy:
        storage = STATE / "storage"
        if forget_iso:
            shutil.rmtree(storage, ignore_errors=True)
            say("removed the disk and the ISO — the next `up` downloads Windows again")
        elif storage.is_dir():
            for name in DISK_FILES:
                (storage / name).unlink(missing_ok=True)
            kept = next(storage.glob("*.iso"), None)
            say("removed the disk" + (f"; kept {kept.name}" if kept else ""))
    return code


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="targets: omarchy (the developer's VM, default) | box (a throwaway container)",
    )
    parser.add_argument("--target", choices=("omarchy", "box"), default="omarchy")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("up", help="start the throwaway box (box only)")
    waiter = sub.add_parser("wait", help="block until the target answers")
    waiter.add_argument("--timeout", type=int, default=2700)
    provisioner = sub.add_parser("provision", help="(re-)run provision.ps1 in the guest")
    provisioner.add_argument(
        "--print-bootstrap",
        action="store_true",
        help="print the line to type into the guest when there is no way in yet",
    )
    sub.add_parser("sync", help="copy this worktree into the guest")
    sub.add_parser("venv", help="uv sync --locked in the guest")
    checker = sub.add_parser("check", help="pytest, ruff, mypy — all three or the ones named")
    checker.add_argument("names", nargs="*", choices=[*CHECKS, []], default=[])
    checker.add_argument("extra", nargs=argparse.REMAINDER)
    sub.add_parser("build", help="the PyInstaller build, and a smoke run of it")
    sub.add_parser("render", help="the render_*.py screenshot scripts, offscreen")
    window = sub.add_parser("window", help="open dpw on the real desktop and photograph it")
    window.add_argument("--after", type=int, default=12, help="seconds to wait before the shot")
    collector = sub.add_parser("collect", help="bring screenshots and logs back")
    collector.add_argument("--out", type=Path, default=STATE / "results")
    cleaner = sub.add_parser("clean", help="give the disk back")
    cleaner.add_argument("--all", action="store_true", help="the tool caches and host logs too")
    sub.add_parser("status", help="what the target has, and what it is using")
    downer = sub.add_parser("down", help="stop the throwaway box (box only)")
    downer.add_argument("--destroy", action="store_true", help="delete the disk as well")
    downer.add_argument(
        "--forget-iso",
        action="store_true",
        help="with --destroy, throw the cached Windows ISO away too (an 8 GB download)",
    )
    downer.add_argument("--yes", action="store_true")
    sub.add_parser("all", help="sync, venv, the three checks, build, render, collect")

    args = parser.parse_args(argv)
    target = target_for(args.target)
    box = args.target == "box"

    if args.verb == "up":
        return do_up()
    if args.verb == "down":
        return do_down(target, destroy=args.destroy, yes=args.yes, forget_iso=args.forget_iso)
    if args.verb == "wait":
        return do_wait(target, args.timeout)
    if args.verb == "status":
        return do_status(target)
    if args.verb == "provision" and args.print_bootstrap:
        # Before the readiness gate below: this exists precisely for a guest that cannot be
        # reached, and staging the payload is the half of provisioning the host can still do.
        payload = target.share / "dplanner"
        payload.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HARNESS / "provision.ps1", payload / "provision.ps1")
        shutil.copyfile(HARNESS / "runner.ps1", payload / "runner.ps1")
        say(f"staged into {payload}\n\nType this into the guest, once:\n")
        say("    " + bootstrap_line(target, with_ssh=box))
        return 0

    trouble = target.ready()
    if trouble:
        raise SystemExit(f"{target.name}: {trouble}")

    if args.verb == "provision":
        return do_provision(target, with_ssh=box)
    if args.verb == "sync":
        return do_sync(target)
    if args.verb == "venv":
        sync_venv = f"Set-Location {GUEST_TREE}\nuv sync --locked\nexit $LASTEXITCODE"
        return target.run(sync_venv, "venv")
    if args.verb == "check":
        extra = [word for word in args.extra if word != "--"]
        return do_check(target, args.names, extra)
    if args.verb == "build":
        return do_build(target)
    if args.verb == "render":
        return do_render(target)
    if args.verb == "window":
        return do_window(target, args.after)
    if args.verb == "collect":
        return do_collect(target, args.out)
    if args.verb == "clean":
        return do_clean(target, everything=args.all)

    steps = (
        ("sync", lambda: do_sync(target)),
        ("venv", lambda: target.run(f"Set-Location {GUEST_TREE}\nuv sync --locked", "venv")),
        ("check", lambda: do_check(target, (), ())),
        ("build", lambda: do_build(target)),
        ("render", lambda: do_render(target)),
        ("collect", lambda: do_collect(target, STATE / "results")),
    )
    outcome = []
    for name, step in steps:
        began = time.time()
        code = step()
        outcome.append((name, code, int(time.time() - began)))
    say("\n=== summary ===")
    for name, code, seconds in outcome:
        say(f"  {'ok  ' if code == 0 else 'FAIL'}  {name:<8} {seconds}s")
    disk_line(target)
    return max(code for _, code, _ in outcome)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
