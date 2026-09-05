"""Command line entry point.

Catnector is a GUI application. This exists so an operator can answer "what
version are you running?" and "is the rig side working?" without opening it,
and so a packaged build has something to check in CI.
"""

from __future__ import annotations

import argparse
import platform
import sys

from . import PROTOCOL_VERSION, __version__


def version_report() -> str:
    """The lines a bug report should start with."""
    return "\n".join(
        [
            f"catnector {__version__}",
            f"  protocol  {PROTOCOL_VERSION}",
            f"  python    {platform.python_version()} ({sys.implementation.name})",
            f"  platform  {platform.system()} {platform.release()} ({platform.machine()})",
            f"  packaged  {'yes' if getattr(sys, 'frozen', False) else 'no'}",
        ]
    )


def check_rig() -> int:
    """Prove rig control works, with no radio, cable or site involved.

    Worth having for its own sake — it is the difference between "catnector
    is broken" and "my cable is unplugged" — and it is what verifies that a
    packaged build can actually reach the hamlib it ships with.
    """
    from .rig import (
        DUMMY_MODEL,
        NetRigctlBackend,
        RigctldOptions,
        RigctldProcess,
        RigError,
        find_executable,
    )
    from .rig.daemon import EXECUTABLE

    try:
        executable = find_executable(EXECUTABLE)
    except RigError as exc:
        print(f"rigctld: NOT FOUND\n  {exc}")
        return 1
    print(f"rigctld: {executable}")

    try:
        with RigctldProcess(RigctldOptions(model=DUMMY_MODEL)) as daemon:
            version = ".".join(str(part) for part in daemon.version or ())
            print(f"  hamlib {version or 'unknown'}, listening on {daemon.port}")
            with NetRigctlBackend(port=daemon.port, hamlib_version=daemon.version) as rig:
                peer = rig.peer
                print(
                    f"  connected: protocol {peer.protocol_version}, "
                    f"{'VFO mode' if peer.vfo_mode else 'plain mode'}"
                )
                rig.set_frequency(14195000)
                rig.set_mode("USB", 2400)
                state = rig.read_state()
                print(f"  simulated radio at {state.freq_hz} Hz {state.mode}")
                if state.freq_hz != 14195000:
                    print("  UNEXPECTED: the radio did not take the frequency")
                    return 1
    except RigError as exc:
        print(f"  FAILED: {exc}")
        return 1

    print("rig control works.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catnector",
        description="Stage your rig's frequency and mode from a spotting site. "
        "Never transmits.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="show version and environment information, then exit",
    )
    parser.add_argument(
        "--config-dir",
        action="store_true",
        help="print the configuration directory, then exit",
    )
    parser.add_argument(
        "--check-rig",
        action="store_true",
        help="check rig control against a simulated radio, then exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.version:
        print(version_report())
        return 0

    if args.config_dir:
        from .paths import config_dir

        print(config_dir())
        return 0

    if args.check_rig:
        print(version_report())
        print()
        return check_rig()

    from .gui import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
