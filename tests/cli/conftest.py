"""The CLI over a **real** read record — the fixture the two gate files share.

Every other CLI test runs behind a record with no file, which refuses nothing and writes
nothing (``tests/conftest.py``'s ``registry``). The gates themselves need the real thing,
so this builds one over the test's own ``tmp_path``: the only place in the suite where a
read is ever recorded, and never the per-user file.
"""

from io import StringIO

import pytest


@pytest.fixture
def gated_cli(workspace, cli_library, tmp_path):
    """The CLI with both doors live: the topology before a graph edit, the house format
    before a test body. It opens with one project, ``Discovery``, and nothing read."""
    from dplanner.cli.command import CliRegistry
    from dplanner.cli.gate import ReadRecord
    from dplanner.cli.main import run
    from dplanner.modules import default_cli_commands, default_module_formats

    registry = CliRegistry()
    registry.register_all(default_cli_commands(reads=ReadRecord(tmp_path / "gate" / "reads.json")))

    def invoke(*argv, expect=0, stdin=""):
        import sys

        out, err = StringIO(), StringIO()
        real = sys.stdin
        sys.stdin = StringIO(stdin)
        try:
            code = run(
                registry,
                default_module_formats(),
                ["--library", str(cli_library), *argv],
                out,
                err,
            )
        finally:
            sys.stdin = real
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    invoke("project", "create", "Discovery", "--dir", str(workspace / "discovery"))
    return invoke
