# Installing catnector

Catnector sets your radio's **frequency and mode**. It never transmits.

## Linux — AppImage

Download `catnector-<version>-x86_64.AppImage` from
[Releases](https://github.com/sysmatt/catnector/releases), then:

```sh
chmod +x catnector-*.AppImage
./catnector-*.AppImage
```

No installation and no package manager. Hamlib is bundled — you do **not**
need to install it separately.

**"Cannot mount AppImage" or "dlopen(): error loading libfuse.so.2".**
Ubuntu 24.04 and other recent distributions no longer ship the FUSE 2
library that AppImages use. Either install it (`sudo apt install libfuse2t64`)
or run without it:

```sh
./catnector-*.AppImage --appimage-extract-and-run
```

**Serial port permission.** Most distributions restrict serial devices to a
group. If catnector says it cannot open your radio:

```sh
sudo usermod -a -G dialout $USER
```

Then **log out and back in**. A new terminal is not enough — group membership
is only applied at login. Some distributions use `uucp` instead of `dialout`;
catnector names the right one when it reports the problem.

## Windows — single executable

Download `catnector.exe` and run it. Hamlib is bundled.

**"Windows protected your PC."** The download is not code-signed, so
SmartScreen warns about it. Choose **More info → Run anyway**. Signing is
under consideration — see `docs/PLANNING.md` §9.1 for what it costs and why
it has not been done yet.

**USB-serial drivers.** Most radios and interfaces need the driver for their
USB chip — CP210x (Silicon Labs), FTDI, or CH340. If Windows shows an
unknown device when the radio is plugged in, install that driver first.

## macOS — from source, for now

There is no macOS download yet, deliberately: an unsigned application bundle
is blocked by Gatekeeper in a way that is genuinely painful to work around,
and shipping one would look broken. See `docs/PLANNING.md` §9.1.

In the meantime, with Python 3.10 or newer:

```sh
pipx install catnector
brew install hamlib
catnector
```

That path involves no downloaded bundle, so Gatekeeper is not involved at
all.

## Any platform — from PyPI

```sh
pipx install catnector
```

You will need hamlib installed yourself (`apt install libhamlib-utils`,
`brew install hamlib`, or the official Windows build), since the wheel does
not bundle it.

## Checking it works, before blaming your cable

```sh
catnector --check-rig
```

This drives a *simulated* radio using the hamlib that catnector will use for
a real one. If it passes, rig control is working and any problem is with the
cable, the port, or the radio's settings.

```
catnector --version       # what to quote in a bug report
catnector --config-dir    # where rigs.ini and sites.ini live
```

## Configuration

Two plain-text files, in the directory `--config-dir` prints:

| File | Contents | Safe to copy? |
|---|---|---|
| `rigs.ini` | Your radios | Yes — no credentials |
| `sites.ini` | Site tokens | **No — these are passwords** |

They are separate so you can copy your radios to a second computer without
copying your credentials. `sites.ini` is created readable only by you; keep
it that way.

## Building it yourself

```sh
uv sync --all-groups
uv run pytest
uv run pyinstaller packaging/catnector.spec --noconfirm
./packaging/build_appimage.sh          # Linux only; fetches appimagetool
```

Install hamlib first, so the build has something to bundle. Without it the
build still works, but the result relies on hamlib being installed on the
machine that runs it.
