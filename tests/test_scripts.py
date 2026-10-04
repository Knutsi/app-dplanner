"""Every script under ``scripts/`` still imports.

mypy's configured files leave ``scripts/`` out — its render scripts reach into views by duck
typing, and checking them strictly is its own piece of work — so nothing else notices when
a refactor renames what a script imports, until somebody runs it for a screenshot. Importing
each one is the cheap half of that check: a renamed or removed name fails here, in the suite.

Each script is imported in **one child process**, never in the worker: the render scripts
set ``QT_QPA_PLATFORM`` and friends at import, and a worker's environment is not theirs to
change. A script's ``__main__`` guard keeps the import from rendering anything.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "scripts"

PROBE = """
import importlib.util, sys, traceback
from pathlib import Path

failed = []
for path in sorted(Path(sys.argv[1]).glob("*.py")):
    spec = importlib.util.spec_from_file_location(f"_script_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # A dataclass looks its module up while it is defined.
    try:
        spec.loader.exec_module(module)
    except BaseException:
        failed.append(f"{path.name}\\t{traceback.format_exc(limit=1).strip().splitlines()[-1]}")
print("\\n".join(failed))
"""

# Scripts that stopped importing before this check existed, each with what removed its name.
# A ratchet: the list may only shrink — mending one fails the test until it is taken off.
KNOWN_BROKEN = {
    # `usage.Usage`, `record` and `row_for` went when usage became a harvested ledger.
    "render_briefing_size.py",
    # `sync.service.PUBLISHING` went when reports stopped being written on Save.
    "render_signalling.py",
}


def test_every_script_imports() -> None:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": ""}
    env["PYTHONPATH"] = os.pathsep.join([str(SCRIPTS), str(ROOT / "src"), str(ROOT)])
    done = subprocess.run(
        [sys.executable, "-c", PROBE, str(SCRIPTS)],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr
    failed = dict(line.split("\t", 1) for line in done.stdout.splitlines() if line)
    newly = {name: why for name, why in failed.items() if name not in KNOWN_BROKEN}
    assert not newly, "scripts that no longer import:\n" + "\n".join(
        f"{name}: {why}" for name, why in newly.items()
    )
    assert set(failed) == KNOWN_BROKEN, "mended — take it off KNOWN_BROKEN"
