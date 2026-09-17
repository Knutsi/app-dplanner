---
name: dplanner-install
description: Install, update or repair DPlanner on this machine — git and uv, a source checkout, then `dplanner install all` — on Linux, macOS or Windows. Use when asked to install, set up, update or remove DPlanner, or when the `dplanner` command is not on PATH.
---

# Installing DPlanner

DPlanner is a development planner: a library of projects, each a graph of steps carrying
aspects, kept as plain files in a git repository and driven by a coding agent through the
`dplanner` command as readily as by a person through its desktop app. Source and
documentation: https://github.com/Knutsi/app-dplanner

## Before anything else: tell the user what they are getting

DPlanner is a **work in progress**. Say so to the user in your own words before you install
anything, and go on only once they have taken it in:

- Its file formats change without notice. A plan written today may not open in a later
  build, and **nothing about compatibility between versions is promised in any way**.
- Its feature set is not stable. Features are added, reshaped and removed between builds.
- It is installed from a source checkout that tracks the repository, not from a release.

If the user does not want that, stop here.

## 1. What is already here

```
git --version
uv --version
dplanner --version
```

If `dplanner` already resolves, skip to *Updating*. Otherwise note which of `git` and `uv`
are missing; those are the only two things to install by hand. Python is not your job: uv
fetches the interpreter DPlanner needs on its own.

## 2. The toolchain: git and uv

Use the package manager this machine already has. Never install a package manager in order
to install a package, and never call one that is not on PATH. **Ask before running anything
with `sudo` or anything that installs system-wide**, and show the exact line first.

**Windows** (PowerShell; open a *new* terminal afterwards so PATH is re-read):

```
winget install --id Git.Git -e
winget install --id astral-sh.uv -e
```

**macOS**, with Homebrew:

```
brew install git uv
```

Without Homebrew, `xcode-select --install` provides git and uv's own installer is
`curl -LsSf https://astral.sh/uv/install.sh | sh`.

**Linux**: git from the distribution's manager, uv from the distribution when it packages
it, otherwise from uv's installer.

| Family | git | uv |
|---|---|---|
| Arch and derivatives | `sudo pacman -S git` (or `yay -S git`) | `sudo pacman -S uv` |
| Debian, Ubuntu | `sudo apt install git` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Fedora, RHEL, CentOS | `sudo dnf install git` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| openSUSE | `sudo zypper install git` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Alpine | `sudo apk add git` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

Read the family from `/etc/os-release` (`ID`, then `ID_LIKE`): a derivative is its parent.

## 3. Get DPlanner

Ask the user where the checkout should live, suggesting `~/Code/app-dplanner` (on Windows
`%USERPROFILE%\Code\app-dplanner`). Then:

```
git clone https://github.com/Knutsi/app-dplanner <that directory>
cd <that directory>
uv run dplanner install all
```

`install all` is the one act that installs DPlanner, and it does three things, reporting
each rather than stopping at the first failure:

- the `dplanner` command, as an editable uv tool install that tracks the checkout;
- a launcher in the applications menu (a `.desktop` entry on Linux, an app bundle in
  `~/Applications` on macOS, a Start Menu shortcut on Windows);
- the skill that teaches an agent to drive DPlanner, written into every skills directory an
  agent reads (`~/.claude/skills/dplanner` for Claude Code and OpenCode,
  `~/.agents/skills/dplanner` for Codex).

Run it from the checkout you cloned, never from a git worktree: the installer refuses to
point the command into one and says so. Read what it printed; a piece that failed says why.

## 4. Check the result

Open a new shell so `dplanner` resolves (uv's `uv tool update-shell` adds its directory to
PATH if it is not there), then:

```
dplanner install status     # the command, the launcher and the skill: all three "installed"
dplanner checklist show     # what else this machine needs; exits 1 while something required is missing
```

Fix every **required** row the checklist reports — git, the command and the skill; the rest
is advice. Each row that has a fix names the line *this* machine would run. Finish by
telling the user that DPlanner is in the applications menu, and that their agent now has
the `dplanner` skill and can plan work with it.

## Updating

```
cd <the checkout>
git pull
uv run dplanner install all
```

The command tracks the checkout, so a pull is already the new build; `install all` refreshes
the launcher and rewrites the skill from it.

## Removing

```
dplanner install remove     # the launcher and the skill
uv tool uninstall dplanner  # the command
```

Then delete the checkout. Plans are the user's own repositories and are never touched.
