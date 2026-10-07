"""What each agent account last said about its usage, and whether a launch waits for it.

**An account is a harness on this machine** — one Claude login, one Codex login, per user —
so the file is ``config_dir()/usage-limits.json``, per user and machine, never the plan.
Every supervised turn records what its stream (Claude's ``rate_limit_event``) or its CLI's
own files (Codex's rollout ``rate_limits``) said about the account's windows, and whether
the turn ran into the wall. Two readings follow from it:

- :func:`hold` — **a new headless launch waits** while a window is at or above the
  threshold (:func:`hold_at`, 95 % unless the person chose otherwise) until that window
  resets, or while the account is out. A launch at 97 % would start hours of work into a
  wall; the real limits of 2026-10-04 and 2026-10-07 struck at 98 and 99 %.
- :func:`exhausted` — **nothing else starts on an account that ran out**, until its reset:
  the supervisor parks a turn it would have started instead (``limit``/``held``).

The file is read-modify-written under an OS lock, because every supervisor writes it.
Qt-free: the supervisor, ``agent run`` and the settings page all read it.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dplanner.core.config_dir import config_dir
from dplanner.core.fsio import os_lock, write_atomic
from dplanner.domain.headless import LimitWindow, TurnEnd, resets

LIMITS_FILE = "usage-limits.json"
LOCK_FILE = "usage-limits.lock"
FORMAT = 1
# The share of a window past which a new headless launch waits for its reset.
HOLD_AT = 0.95
# The settings page's choices; 100 % holds only an account that has run out.
HOLD_PRESETS = (0.8, 0.9, 0.95, 1.0)


@dataclass(frozen=True)
class Account:
    """One account's last-known usage."""

    harness: str
    at: str = ""  # When its windows were last reported.
    run: str = ""  # The run whose turn reported them.
    windows: tuple[LimitWindow, ...] = ()
    # When the account comes back, since a turn ran out on it; None while it has not.
    out_until: datetime | None = None


def hold_at(config: Path | None = None) -> float:
    """The threshold a new headless launch waits at, as a share of a window."""
    share = _read(config).get("hold_at")
    if isinstance(share, (int, float)) and not isinstance(share, bool) and 0 < share <= 1:
        return float(share)
    return HOLD_AT


def set_hold_at(share: float, config: Path | None = None) -> None:
    if not 0 < share <= 1:
        raise ValueError(f"a threshold is a share above 0 and at most 1, not {share}")
    _change(lambda data: {**data, "hold_at": share}, config)


def accounts(config: Path | None = None) -> dict[str, Account]:
    raw = _read(config).get("accounts")
    if not isinstance(raw, dict):
        return {}
    return {
        harness: _account(harness, given)
        for harness, given in raw.items()
        if isinstance(given, dict)
    }


def account(harness: str, config: Path | None = None) -> Account:
    return accounts(config).get(harness, Account(harness))


def record_turn(
    harness: str,
    run: str,
    windows: Sequence[LimitWindow],
    end: TurnEnd,
    until: datetime | None,
    produced: bool,
    config: Path | None = None,
) -> None:
    """What one turn said about its account: the windows it reported, if any, and whether
    it ran out (``until`` being when the account comes back) — or produced something, which
    says the account is back. Never raises: the account's telemetry is advice, and a turn
    must not fail for want of somewhere to write it."""

    def changed(data: dict[str, Any]) -> dict[str, Any]:
        known = _account(harness, _raw(data, harness))
        if windows:
            known = replace(known, windows=tuple(windows), at=_now().isoformat(), run=run)
        if end is TurnEnd.LIMIT:
            if until is not None:
                known = replace(known, out_until=until)
        elif produced:
            known = replace(known, out_until=None)
        listed = data.get("accounts")
        return {
            **data,
            "accounts": {**(listed if isinstance(listed, dict) else {}), harness: _to_json(known)},
        }

    with suppress(OSError):
        _change(changed, config)


def exhausted(
    harness: str, now: datetime | None = None, config: Path | None = None
) -> datetime | None:
    """When the account that ran out comes back; None when it has not run out, or is back."""
    until = account(harness, config).out_until
    return until if until is not None and until > (now or _now()) else None


def last_reset(
    harness: str, now: datetime | None = None, config: Path | None = None
) -> datetime | None:
    """When the account's fullest window last said it resets, if that is still to come: the
    reset of a limit whose own turn reported none."""
    reset = resets(account(harness, config).windows)
    return reset if reset is not None and reset > (now or _now()) else None


def hold(
    harness: str,
    label: str,
    threshold: float | None = None,
    now: datetime | None = None,
    config: Path | None = None,
) -> str:
    """Why a new headless launch on the account waits, or "" when it may go. ``label`` is
    the agent's name, as the reason says it."""
    now = now or _now()
    threshold = hold_at(config) if threshold is None else threshold
    known = account(harness, config)
    if known.out_until is not None and known.out_until > now:
        at = clock(known.out_until, now)
        return f"{label} ran out of usage; new headless launches wait for its reset at {at}"
    full = [w for w in known.windows if w.used >= threshold and w.resets and w.resets > now]
    if not full:
        return ""
    fullest = max(full, key=lambda w: w.used)
    assert fullest.resets is not None
    return (
        f"{label} is at {fullest.used:.0%} of its {fullest.name.replace('_', '-')} window;"
        f" new headless launches wait for its reset at {clock(fullest.resets, now)}"
        f" (Settings ▸ Agent profiles holds them at {threshold:.0%})"
    )


def clock(moment: datetime, now: datetime | None = None) -> str:
    """A reset in the reader's local time: the time today, with the date on another day."""
    local, today = moment.astimezone(), (now or _now()).astimezone()
    return f"{local:%H:%M}" if local.date() == today.date() else f"{local:%a %d %b %H:%M}"


def parse(stamp: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment and moment.tzinfo is None else moment


# -- the file ---------------------------------------------------------------------------------


def limits_file(config: Path | None = None) -> Path:
    return (config or config_dir()) / LIMITS_FILE


def _read(config: Path | None) -> dict[str, Any]:
    try:
        raw = json.loads(limits_file(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _change(change: Callable[[dict[str, Any]], dict[str, Any]], config: Path | None) -> None:
    path = limits_file(config)
    with os_lock(path.parent / LOCK_FILE, wait=True):
        data = {**change(_read(config)), "format": FORMAT}
        write_atomic(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _raw(data: Mapping[str, Any], harness: str) -> Mapping[str, Any]:
    listed = data.get("accounts")
    given = listed.get(harness) if isinstance(listed, dict) else None
    return given if isinstance(given, dict) else {}


def _account(harness: str, raw: Mapping[str, Any]) -> Account:
    listed = raw.get("windows")
    windows = tuple(
        LimitWindow(str(w["name"]), float(w["used"]), parse(str(w.get("resets") or "")))
        for w in (listed if isinstance(listed, list) else ())
        if isinstance(w, dict)
        and isinstance(w.get("name"), str)
        and isinstance(w.get("used"), (int, float))
        and not isinstance(w.get("used"), bool)
    )
    return Account(
        harness,
        at=str(raw.get("at") or ""),
        run=str(raw.get("run") or ""),
        windows=windows,
        out_until=parse(str(raw.get("out_until") or "")),
    )


def _to_json(known: Account) -> dict[str, Any]:
    data: dict[str, Any] = {
        "at": known.at,
        "run": known.run,
        "windows": [
            {"name": w.name, "used": w.used, "resets": w.resets.isoformat() if w.resets else ""}
            for w in known.windows
        ],
    }
    if known.out_until is not None:
        data["out_until"] = known.out_until.isoformat()
    return data


def _now() -> datetime:
    return datetime.now(UTC)
