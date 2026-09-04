# catnector

A cross-platform desktop tool that lets a spotting site stage your ham
radio — setting its **frequency and mode** to match a spot, and optionally
tracking that station as it moves.

**Catnector never transmits.** There is no PTT, keying, or power control,
and there never will be. It stages the radio; the licensed operator makes
the contact. A compromised token can retune a receiver, not put a signal on
the air.

## Status

Pre-alpha. The design is settled and the protocol is finished; the
application is being built milestone by milestone. See
[`docs/PLANNING.md`](docs/PLANNING.md) — §15 is the milestone ladder.

| | | |
|---|---|---|
| **M0** | Repo scaffold | ✅ done |
| **M1** | Rig control layer, headless | next |
| **M2** | GUI and rig profiles | |
| **M3** | Site connection | |
| **M4** | Telemetry and control — **MVP** | |
| **M5** | Packaging | |

## How it talks to your radio

Through hamlib's `rigctld`, over TCP — never by opening the serial port
itself. That matters because a serial port has exactly one owner: if you are
being followed, you are *operating*, and WSJT-X or a logger very likely
already holds that port. Catnector must never be the process that locks you
out of the software you actually make contacts with.

The upshot is that flrig, FlexRadio and the SmartSDR slices are ordinary
entries in the rig picker rather than special cases, and catnector can join
a `rigctld` you are already running. See `docs/PLANNING.md` §8.

## How it talks to a website

Over an open protocol — plain WSS carrying JSON — specified in its own
repository, [catnector-protocol](https://github.com/sysmatt/catnector-protocol).
HamQSY runs the reference server, but nothing about the protocol is
HamQSY-specific: any site can stand up a compatible endpoint, and there is a
conformance checker to tell them whether they got it right.

## Development

```sh
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run catnector --version
```

`uv` is not required — the project is a standard PEP 621 package, so
`pip install -e ".[dev]"` works equally well. The lockfile exists so that a
bug report against a shipped binary can be reproduced.

## Licence

GPLv3 — see [LICENSE](LICENSE). Deliberate copyleft: the ecosystem this is
aimed at is other ham and community-run projects, not companies, so the
friction copyleft adds to commercial adoption is not a real cost here.
