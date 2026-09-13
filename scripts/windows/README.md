# The Windows target

DPlanner has Windows code paths — the Start Menu shortcut, Windows Terminal, the `dpw`
gui-script, the Credential Manager keychain, `_windows_process_alive` — and Linux can run
almost none of them. This directory is how they get checked.

**It is a rare, manual check, and there is no CI.** The cheap guard that runs on every machine
in between is `uv run mypy --platform win32`, one of the four checks in `CLAUDE.md`: mypy skips
a `sys.platform == "win32"` branch entirely on Linux, so without it that code is read by
nobody. The VM is for everything types cannot answer.

```bash
uv run python scripts/windows_check.py status     # what the target has, and what it is using
uv run python scripts/windows_check.py all        # sync, three checks, build, screenshots
uv run python scripts/windows_check.py clean      # give the disk back
```

Every verb stands alone, because the fix loop is *sync, run one check, read it, repeat*:

```bash
uv run python scripts/windows_check.py sync
uv run python scripts/windows_check.py check pytest -- -x tests/cli
```

## Two targets

### `--target omarchy` (the default)

Omarchy's own Windows VM — `omarchy-windows-vm launch` — installed, persistent, the
developer's account. Using it costs no extra disk, no extra RAM and no install. The harness
never starts, stops, recreates or reconfigures it; `down` refuses outright.

It publishes no SSH port, and adding one would mean recreating a container that is not this
check's to recreate. So the transport is the shared folder that container already binds.
**Start the runner once, in a PowerShell window on the VM's desktop:**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File Z:\dplanner\runner.ps1
```

Leave that window open. It watches `Z:\dplanner\inbox` for jobs and writes each log and exit
code back to `outbox`. Because *you* started it on the desktop, everything it runs is already
in the interactive session — which is why `window` can open `dpw` where you can see it and
screenshot it. A process started over SSH cannot: it lands in the SSH logon session, paints to
a desktop nobody is looking at, and `CopyFromScreen` there returns black.

First time, run `provision` to put git and uv in the VM.

### `--target box`

A throwaway `dockurr/windows` container, driven over SSH. Isolated, fully scriptable, and it
costs a 20–30 minute first install, ~12 GB of RAM while running and tens of GB of disk.

```bash
uv run python scripts/windows_check.py --target box up     # ~25 min the first time
uv run python scripts/windows_check.py --target box wait
uv run python scripts/windows_check.py --target box all
uv run python scripts/windows_check.py --target box down            # stop; cheap to restart
uv run python scripts/windows_check.py --target box down --destroy --yes   # the disk too
```

`down --destroy` keeps the downloaded Windows ISO — 8 GB against a 25-minute install — so the
next `up` reinstalls without fetching it; `--forget-iso` throws that away as well. And when
provisioning itself is what failed, there is no sshd to re-run it with:
`provision --print-bootstrap` stages the payload and prints the one line to type into the
viewer at http://localhost:8007, once.

Ports are `2222` (SSH), `8007` (web viewer) and `3390` (RDP) — 8006 and 3389 belong to the
Omarchy VM. All three bind to the loopback: this box has an administrator account with a
throwaway password and no updates, and it must not be on the LAN.

**Publishing a Docker port does not reach the guest.** qemu-docker's `getUserPorts()` forwards
only 3389 by default in Windows boot mode and takes every other guest port from the
`USER_PORTS` environment variable, which the compose file sets. It also silently drops any
port under 1024 the container cannot bind, which is why sshd listens on 2222 rather than 22 —
the failure mode is a warning in `docker compose logs` and an SSH that never answers.

## Where things live, and what they cost

Nothing mutable is in the repository. The VM disk, the OEM payload and the rsync staging
directory all sit under `~/.local/share/dplanner-windows/` — rsyncing the worktree into a
directory inside the worktree recurses, and a throwaway git worktree must not take a 64 GB
disk with it when it is removed.

`status` prints what the check occupies in the guest; `clean` removes the synced tree, the
build and the logs, and `clean --all` takes the uv cache with it. `down --destroy` is the only
expensive button and it asks.

On btrfs the container warns about `/storage`, and it is right to: a raw disk image under
copy-on-write with random writes fragments badly. `chattr +C` on the storage directory
*before* the first boot turns CoW off for files created in it — after the image exists it is
too late for that image. It has not been measured here, and the install worked without it.

## The files

| File | What it is |
|---|---|
| `docker-compose.yml` | the throwaway box: image, ports, KVM, the binds |
| `install.bat` | the one-shot handover, run once at the end of the unattended install |
| `provision.ps1` | **all** the guest logic — git, uv, Python, sshd — and re-runnable |
| `runner.ps1` | the shared-folder job loop, for a VM with no SSH |

`install.bat` decides nothing on purpose. It runs exactly once per disk, in a context with no
console to watch and no way to retry without reinstalling Windows, so everything that can go
wrong lives in `provision.ps1`, which `windows_check.py provision` re-runs as often as it
takes.

**The guest scripts are ASCII, and `tests/test_windows_harness.py` keeps them so.** Windows
PowerShell 5.1 reads a `.ps1` with no byte-order mark as ANSI, and an em dash in a
double-quoted string ends the string early — the whole file then fails to parse, with an
error pointing thirty lines from the character that caused it. That is how the first
provisioning run of the box died, and nothing on Linux shows it.

## Licences

`dockurr/windows` is MIT, pinned to `6.05`. It needs `/dev/kvm`, `/dev/net/tun` and
`NET_ADMIN`, and it downloads a Microsoft ISO and installs it with Microsoft's generic *trial*
keys: the guest is an unactivated evaluation install and nothing here redistributes Windows.
Unactivated Windows 11 Pro runs indefinitely with a desktop watermark, neither of which affects
a check; `status` prints the licence state every time it runs, so an edition that *does* expire
is never a surprise.
