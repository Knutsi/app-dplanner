"""Probe how claude, codex and opencode fail when run headless, at no cost.

Each probe runs one CLI in a throwaway HOME (so it never sees the developer's login),
pointed at `fake_api.py` serving one failure, and records what the CLI did: exit code,
how long it took, its stdout events and its stderr. Nothing reaches a real model API, so
nothing is spent. The records land in `out/` and are what `classify.py` is built on.

    uv run python run_probes.py <scratch dir> [probe-name ...]
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
SERVER_MODES = ["401", "403", "404model", "credit", "429", "529", "500", "garbage", "hang"]
TIMEOUT_S = 330.0
KILL_AFTER_S = 8.0
PROMPT = "Reply with the single word: ok"


@dataclass(frozen=True)
class Probe:
    cli: str
    mode: str  # noauth | a fake_api mode | sigterm | sigkill (a hanging API, then a signal)

    @property
    def name(self) -> str:
        return f"{self.cli}-{self.mode}"

    @property
    def server_mode(self) -> str | None:
        if self.mode == "noauth":
            return None
        return "hang" if self.mode in ("sigterm", "sigkill") else self.mode


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def binary(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise SystemExit(f"{name} is not on PATH")
    return found


def setup(probe: Probe, home: Path, port: int | None) -> tuple[list[str], dict[str, str]]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "TERM": "dumb",
        "LANG": "C.UTF-8",
        "NO_COLOR": "1",
    }
    base = f"http://127.0.0.1:{port}" if port else None
    if probe.cli == "claude":
        if base:
            env["ANTHROPIC_API_KEY"] = "sk-ant-bogus-probe"
            env["ANTHROPIC_BASE_URL"] = base
        argv = [
            binary("claude"),
            "-p",
            PROMPT,
            "--output-format",
            "stream-json",
            "--verbose",
            "--bare",
            "--max-turns",
            "1",
        ]
        return argv, env
    if probe.cli == "codex":
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True)
        env["CODEX_HOME"] = str(codex_home)
        if base:
            env["FAKE_KEY"] = "sk-bogus-probe"
            (codex_home / "config.toml").write_text(
                'model = "gpt-5.5"\nmodel_provider = "fake"\n\n[model_providers.fake]\nname = "fake"\n'
                f'base_url = "{base}/v1"\nenv_key = "FAKE_KEY"\nwire_api = "responses"\n'
            )
        argv = [
            binary("codex"),
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            PROMPT,
        ]
        return argv, env
    if probe.cli == "opencode":
        if base:
            config = home / "opencode.json"
            config.write_text(
                json.dumps(
                    {
                        "$schema": "https://opencode.ai/config.json",
                        "provider": {
                            "anthropic": {"options": {"baseURL": f"{base}/v1", "apiKey": "sk-ant-bogus-probe"}}
                        },
                    }
                )
            )
            env["OPENCODE_CONFIG"] = str(config)
        argv = [binary("opencode"), "run", "--format", "json", "-m", "anthropic/claude-sonnet-4-5", PROMPT]
        return argv, env
    raise ValueError(probe.cli)


def scrub(text: str, home: Path) -> str:
    return text.replace(str(home), "$HOME").replace(str(Path.home()), "~")


def clip(line: str, limit: int = 4000) -> str:
    return line if len(line) <= limit else line[:limit] + f"…(+{len(line) - limit} chars)"


def run(probe: Probe, scratch: Path) -> dict[str, object]:
    home = scratch / probe.name
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True)
    port = free_port() if probe.server_mode else None
    server = None
    if port:
        server = subprocess.Popen(
            [sys.executable, str(HERE / "fake_api.py"), str(port), probe.server_mode or ""],
            stdout=subprocess.DEVNULL,
            stderr=open(home / "server.log", "w"),
        )
        time.sleep(0.5)
    argv, env = setup(probe, home, port)
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=home,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    sent: str | None = None
    timed_out = False
    try:
        if probe.mode in ("sigterm", "sigkill"):
            try:
                proc.wait(timeout=KILL_AFTER_S)
            except subprocess.TimeoutExpired:
                sig = signal.SIGTERM if probe.mode == "sigterm" else signal.SIGKILL
                sent = sig.name
                proc.send_signal(sig)
        out, err = proc.communicate(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
    elapsed = time.monotonic() - started
    if server:
        server.terminate()
        server.wait()
    requests = (home / "server.log").read_text().count("POST") if port else 0
    stdout = [clip(line) for line in scrub(out.decode(errors="replace"), home).splitlines()]
    stderr = [clip(line) for line in scrub(err.decode(errors="replace"), home).splitlines()]
    record: dict[str, object] = {
        "probe": probe.name,
        "cli": probe.cli,
        "mode": probe.mode,
        "argv": [Path(argv[0]).name, *argv[1:]],
        "exit": proc.returncode,
        "signal_sent": sent,
        "timed_out_after_s": TIMEOUT_S if timed_out else None,
        "seconds": round(elapsed, 1),
        "requests_seen": requests,
        "stdout_lines": len(stdout),
        "stdout_head": stdout[:25],
        "stdout_tail": stdout[-15:] if len(stdout) > 25 else [],
        "stderr_tail": stderr[-30:],
    }
    OUT.mkdir(exist_ok=True)
    (OUT / f"{probe.name}.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(
        f"{probe.name:24} exit={proc.returncode} {elapsed:6.1f}s requests={requests} {'TIMEOUT' if timed_out else ''}",
        flush=True,
    )
    return record


def all_probes() -> list[Probe]:
    modes = ["noauth", *SERVER_MODES, "sigterm", "sigkill"]
    return [Probe(cli, mode) for cli in ("claude", "codex", "opencode") for mode in modes]


def main() -> None:
    scratch = Path(sys.argv[1]).resolve()
    wanted = set(sys.argv[2:])
    probes = [p for p in all_probes() if not wanted or p.name in wanted]
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda p: run(p, scratch), probes))


if __name__ == "__main__":
    main()
