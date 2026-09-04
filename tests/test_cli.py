"""M0 scaffold tests.

There is very little to test yet, deliberately. What these do assert is that
the package is importable, installed, and that its version reporting works —
which is what every later milestone lands on top of.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import catnector
from catnector.cli import main, version_report


def test_package_reports_a_real_version():
    """A source-tree fallback means an uninstalled package still imports."""
    assert catnector.__version__
    assert catnector.__version__ != "0.0.0+unknown", (
        "package is not installed; run 'uv sync' or 'pip install -e .'"
    )


def test_protocol_version_is_one():
    """Bump deliberately, and only alongside catnector-protocol SPEC.md §8.4."""
    assert catnector.PROTOCOL_VERSION == 1


def test_version_report_carries_what_a_bug_report_needs():
    report = version_report()
    assert catnector.__version__ in report
    for field in ("protocol", "python", "platform"):
        assert field in report


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_version_flag_exits_zero(flag, capsys):
    assert main([flag]) == 0
    assert catnector.__version__ in capsys.readouterr().out


def test_module_entry_point_runs():
    """python -m catnector must work, not just the console script."""
    result = subprocess.run(
        [sys.executable, "-m", "catnector", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "catnector" in result.stdout
