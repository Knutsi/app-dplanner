"""A recorder stand-in for the dictation tests: writes flushed samples to stdout until told
to stop, the way each real recorder does — on SIGTERM, on ``q``, never (so ``kill()`` has
to), or not at all (it fails at once). ``quiet`` writes silence, for the level check."""

import sys
import time

SCRIPT = r"""
import signal, struct, sys, threading, time
mode = sys.argv[1]
if mode == "fail":
    sys.stderr.write("no such device\n")
    sys.exit(3)
stop = threading.Event()
if mode == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
else:
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
if mode == "q":
    threading.Thread(target=lambda: (sys.stdin.readline(), stop.set()), daemon=True).start()
out = sys.stdout.buffer
sample = struct.pack("<h", 0 if mode == "quiet" else 12000)
while not stop.is_set():
    out.write(sample * 160)
    out.flush()
    time.sleep(0.01)
"""

CHUNK_BYTES = 320  # One write of the script: 160 signed 16-bit samples.


def recorder(mode: str = "term") -> list[str]:
    return [sys.executable, "-u", "-c", SCRIPT, mode]


def command_text(mode: str = "term") -> str:
    """The same recorder as a command text a settings field could hold."""
    import shlex

    return " ".join(shlex.quote(token) for token in recorder(mode))


def wait_for(app, predicate, timeout=5.0, what="the recorder"):
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, f"{what} never settled"
        app.processEvents()
        time.sleep(0.01)
