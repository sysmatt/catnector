# Catnector — Project Planning

Status: design settled and scoped into milestones (§15); implementation not
yet started. The transport, auth, forward-compatibility, rig-control,
platform, toolchain and safety decisions were settled in this repo on
2026-09-03 and are marked (settled) in their sections.

This doc was originally extracted from `hamqsy`'s `docs/PLANNING.md` on
2026-09-03 — see that repo for the web app's side of the same
protocol/integration (their doc kept its own copy of the shared
protocol/auth/data-model content; nothing was deleted there). Note that the
protocol design that was settled here has since moved to
`catnector-protocol/SPEC.md`, which is normative for both sides; §3, §5.1
and §6 below are now pointers to it plus catnector's own client-side
obligations. `hamqsy`'s planning doc has been reconciled the same way.

## 1. What catnector is

A slim, multi-platform desktop GUI (**Python + PySide6/Qt**) that uses
**Hamlib** to control a locally connected ham radio rig. It:
- Sets **frequency and mode only** — it never keys PTT, it just stages the
  radio for the human to make the actual contact
- Authenticates to a web service via a **bearer token** (see §3) — token
  exchange, not username/password
- Shows a basic connection status indicator ("Connected")
- Supports **multiple rig profiles** so a user can switch rigs quickly —
  needed both because many operators own multiple radios, and because a
  single station/rig may be shared by multiple operators
- Supports **multiple registered site connections** (see §3), not just
  HamQSY — the token exchange and control surface is a generic open
  protocol other spotting sites could stand up their own endpoint for, not
  HamQSY-proprietary

Catnector is meant to be genuinely site-agnostic: HamQSY runs the reference
implementation of the server endpoint it talks to, but any other site
(e.g. a hypothetical POTA.app integration) could implement the same open
protocol on its own backend and interoperate with the same catnector
client, with zero involvement from HamQSY.

**"Catnector" is the final product name** — a "CAT control" + "connector"
pun, immediately readable to the ham community, not so cute it undermines
trust in a tool that touches people's rigs. No rename planned.

## 2. The tune/follow workflow (what catnector executes)

On a connected site's web UI, next to each spot, a user sees a button:
1. **"Tune my rig"** — one-shot: catnector sets the local rig's freq/mode
   to match a spot.
2. After pressing it once, the button becomes **"QSY Follow"** — catnector
   now actively tracks that specific operator: if they change frequency or
   mode, the local rig follows automatically.

**Key constraint: QSY Follow only works if the target is also running
catnector and connected.** Being followable is the entire point of running
catnector while spotted — there's no separate consent step, since a
catnector-connected spot is implicitly "I want people to be able to track
me." A web-only spot (no catnector) never becomes followable.

**Staleness never auto-ends a follow.** If the target's connection goes
stale (missed heartbeats, computer asleep, etc.), that's purely
informational on the site's end — catnector keeps the follow relationship
alive and resumes cleanly if/when telemetry starts flowing again, no
explicit re-subscription needed. A follow only ends on manual unfollow or
the target explicitly un-spotting.

All of this bookkeeping lives **server-side**. Catnector itself has no
concept of a follow — it receives one `set_rig` message and obeys it, and
cannot tell a one-shot tune from a follow update (§3.2).

**One site session / one active follow at a time, per account (settled).**
Not per-rig, per-account. Multi-station scenarios (e.g. club Field Day
operations) don't need more than this — the correct mapping there is one
account per physical station/computer, not one account trying to drive
several rigs at once. True single-operator simultaneous-multi-rig
following (SO2R-style solo dual-rig operating) is a different, harder
feature — see §13 (Future Ideas).

## 3. Catnector ↔ site protocol

**The protocol is specified in full in the `catnector-protocol` repo
(`SPEC.md`, protocol version 1). That document is normative; this section is
not.** What follows is only what catnector, as a client, owes the other end
— plus the client-side reasoning that has no place in a specification.

Where the two disagree, `SPEC.md` wins. If this section drifts, delete it
rather than reconciling it by hand.

Catnector doesn't know or care which "flavour" of site it is talking to. It
speaks the protocol to whatever endpoint the pasted token names.

### 3.1 What catnector must do

| Obligation | `SPEC.md` |
|---|---|
| Decode the `cnx1_` token, verify its checksum, and report a *damaged* token differently from a *rejected* one | §4.1 |
| Fetch `/.well-known/catnector` before connecting; take the WebSocket URL and telemetry interval from it | §4.2 |
| Connect over `wss:` — `localhost` only is exempt, and there is no user-facing "disable TLS" | §5.1 |
| Send the token as `Authorization: Bearer` and offer `Sec-WebSocket-Protocol: catnector.v1` | §5.2–5.3 |
| Send `hello` with the client's feature list; display the callsign and site from `welcome` | §7.1–7.2 |
| Report freq, mode, passband, rig profile name and **rig health**, self-throttled to the negotiated interval | §7.3, §9.1 |
| Apply `set_rig` — or refuse it whole, never in part — and always answer `ack`/`nack` | §7.4, §7.6 |
| Render `follow_state` and never derive behaviour from it | §7.5 |
| Refuse any message naming a `req` field it does not understand | §8.2 |
| Coalesce inbound control: apply the latest, discard the intermediates | §9.2 |
| Ping every 10 s; treat five unanswered as dead | §10 |
| Never auto-reconnect after a terminal close code | §11 |
| Satisfy the client safety requirements — no keying, PTT deferral, range refusal, visible disclosure, a disconnect control | §12 |

The last row is the floor, not the ceiling. §10 of this document is how
catnector actually meets it, and goes further in places.

### 3.2 Why catnector has no concept of a follow

Worth keeping here because it is a *client design* decision that the spec
records only as a consequence.

A one-shot "Tune my rig" and an ongoing QSY Follow update are the same
message. Catnector cannot distinguish them and does not need to: every bit
of follow bookkeeping — who follows whom, one-at-a-time enforcement,
staleness — is server-side (§2, §5). So catnector has no follow state
machine, no subscription logic, and no way for its view of a follow to
disagree with the site's.

Two fields exist purely so the operator is not left guessing why the radio
moved: `source` on each control message, and the separate display-only
`follow_state` push that lets a persistent "Following W1ABC" indicator be
*cleared* when the follow ends. Catnector renders both and acts on neither.

### 3.3 Multiple sites, one at a time

Catnector holds several registered site connections at once — a HamQSY
token and some other site's token, both saved — but **only one is active**,
chosen from a dropdown. Rig profiles are selected independently: the two
choices are orthogonal.

The UI must always show, for the active connection, **which site** it is
talking to and **which callsign** it is authenticated as. Callsigns are
self-asserted and not unique (`SPEC.md` §7.2), so catnector displays
whatever the session resolves to and treats it as a label, never an
identifier.

### 3.4 Reference implementation and conformance (settled)

**The mock site server and a protocol conformance checker live in the
`catnector-protocol` repo, not here.** They are deliverables of the spec,
not fixtures of the client.

This is what turns "open protocol" into "open protocol someone can actually
adopt": a site standing up its own endpoint can run the checker against it
and *know* it is compatible, instead of discovering incompatibilities
through a user's broken rig. A spec document alone has never been enough for
that, and the checker is the cheapest possible substitute for a multi-vendor
standards process (§3).

Consequences for catnector:

- Catnector's own development and CI consume the mock server as a fixture,
  which means the reference implementation is continuously exercised rather
  than bit-rotting alongside the spec.
- Combined with the built-in **Hamlib Dummy** rig profile (§8.1), the whole
  application is developable, testable and demonstrable **with no radio and
  no live site**.
- The localhost TLS carve-out (`SPEC.md` §5.1) exists precisely so this works without
  minting certificates.
- It also gives users a way to prove the site half works before blaming
  their cable.

## 4. Config file format (settled)

**Site connections (bearer tokens) and rig profiles live in separate INI
files**, not one combined config blob. Rationale: ham operators skew
tech-savvy and comfortable editing plain-text config — separate files make
it obvious and low-friction to copy just the piece you want to another
computer (e.g. copy only the rig-profiles file to a laptop that has no
site tokens yet, or only the site-tokens file to a second machine that
already has its own rig set up). Plain, human-readable/editable config is
a deliberate choice for this audience, not an oversight.

### 4.1 Locations and discoverability

Two files — `sites.ini` and `rigs.ini` — in the platform's standard config
directory, with a `CATNECTOR_CONFIG_DIR` environment override.

Qt's `QStandardPaths` was the original intention; implementation used the
platform conventions directly instead, because several `QStandardPaths`
locations require a `QCoreApplication` to exist — which would make
configuration unreadable and untestable outside a running GUI. The resulting
paths are the ones Qt reports.

**The paths must be discoverable in the UI** — a "reveal config folder"
button, not a line buried in a README. The entire rationale above is that
people hand-copy these files between machines; a config format optimized for
copying, whose location is undocumented in the app, defeats itself.

First run creates the directory and writes commented example files rather
than leaving the user to guess the schema.

### 4.2 Token file permissions

`sites.ini` holds bearer tokens in plain text. That is deliberate and stays
— a keyring would destroy exactly the portability §4 is buying. The
mitigations are modest and sufficient:

- **`chmod 0600` on creation**, and **warn on load** if the file is group-
  or world-readable.
- On Windows `os.chmod` is effectively a no-op, so the protection there is
  placing config under the already user-scoped `%APPDATA%`, documented as
  such rather than silently assumed.

## 5. Session uniqueness (settled)

Copying config between machines (§4) creates an obvious failure mode: an
operator accidentally has catnector live and connected on two computers at
once with the same site token. Two simultaneous "live" sessions for one
account is not something the system should allow silently — it's
ambiguous which machine's rig/telemetry is authoritative, and it would
confuse both QSY Follow (which one is the source of truth?) and the site's
connected/rig-selected display.

**Enforced at the account level, server-side: only one active catnector
session per user account at a time, regardless of which token or which
computer.** New connection wins — when a second session authenticates
while one is already active, the server terminates the older session. On
the kicked side, **catnector shows a modal dialog stating the reason
plainly** ("This session was disconnected because…"), rather than just
silently dropping to a disconnected state with no explanation.

### 5.1 Being kicked, and not fighting back

Close codes are specified in `SPEC.md` §11. Catnector's side of it:

**A terminal close code must not auto-reconnect** — `4001` superseded,
`4002` bad token, `4003` version unsupported. Everything else, including
plain network loss, reconnects with exponential backoff and jitter.

The reason is worth remembering when someone later "fixes" the reconnect
logic: two computers sharing one token that both auto-reconnect will
supersede each other indefinitely, each kicking the other, producing a storm
that looks like a network fault and isn't.

On `4001`, catnector shows a **modal stating the reason plainly** — "this
session was disconnected because…" — rather than dropping silently to a
disconnected state the operator has to guess about.

## 6. Telemetry rate limiting

Specified in `SPEC.md` §9.1. Catnector's obligations:

**Self-throttle.** The interval is enforced *in catnector*, not by relying
on the site to reject the excess — catnector never spams an API in the first
place rather than firing requests that get dropped.

**Take the interval from the site.** 1 s is only the default when nothing
says otherwise; the endpoint states what it wants in `/.well-known` and in
`welcome`, so a site's load characteristics or a future faster tier can
change it with no catnector release.

**Report rate is not poll rate.** A serial rig will not reliably answer
inside one second; see §8.4.

## 7. Data model (catnector-local, not server-side)

- **RigProfile** — hamlib model, **connection kind** (serial device,
  network `host:port`, or none), the connection settings that kind implies,
  and a nickname. Independent of which site connection is active. The
  connection kind is not assumed to be serial: hamlib models flrig, Flex and
  the SmartSDR slices as network-link backends (§8.1), so a profile's target
  is `/dev/ttyUSB0` for one rig and `192.168.1.50:4992` for another.
- **SiteConnection** — endpoint hostname (decoded from token), bearer
  token, nickname. User can register several, only one active at a time.

(The server-side data model — User, Callsign, QTH, Spot, FollowSession —
lives in the implementing site's own planning doc, e.g. `hamqsy`'s
`docs/PLANNING.md` §3.2. Catnector doesn't store or need to know that
schema directly, only the protocol messages in §3 above.)

## 8. Rig control layer (settled)

**Catnector talks to the radio over the hamlib `rigctld` network protocol
(TCP), never by opening the serial port itself and never by linking hamlib
in-process.**

The decider is **serial port exclusivity**. A serial port has exactly one
owner, and the operator being followed is *operating* — WSJT-X, a logger, or
flrig is very likely already holding that port. Catnector must never be the
process that locks a user out of the software they actually make contacts
with. `rigctld` is how hams already share one radio between programs, and it
serves multiple simultaneous clients with consistent state (verified: two
sockets against one `rigctld`, freq/mode set on one and read back correctly
on the other).

Everything else follows from that decision rather than motivating it:

- **Pure-pip dependencies.** There is no real hamlib binding on PyPI — the
  `hamlib` and `pyhamlib` names are squatted 0.0.1 stubs containing
  unrelated code. In-process would mean shipping a Python-ABI-pinned SWIG
  `.so` per platform *per Python version*; over TCP the only native artifact
  is a `rigctld` binary we bundle, and PySide6 ships `abi3` wheels.
- **Crash isolation.** A malformed serial response can't take the GUI down.
- **No link-time version coupling.** hamlib is never in catnector's address
  space, so catnector is not married to one hamlib version (see §8.2).
- **Licensing is clean.** Catnector is GPLv3, so bundling GPL `rigctld` is
  unproblematic.

### 8.1 Connection modes

**Managed mode is the entire normal experience.** The user picks their radio
in catnector, exactly as they would in WSJT-X, and catnector launches and
supervises `rigctld` for them. *The user never learns that `rigctld`
exists.* Configuring rigctld separately is explicitly a non-goal.

Because hamlib models network-attached rigs as ordinary backends, this
covers far more than serial radios with no extra catnector code — they are
simply entries in the same rig picker:

| Rig picker entry | hamlib model | Port type |
|---|---|---|
| FT-991, IC-7300, … (the other ~270) | e.g. 1035 | RS-232 |
| **FLRig** | 4 | Network link |
| **FlexRadio 6xxx** | 2036 | Network link |
| **SmartSDR Slice A–H** | 23005–23012 | Network link |
| Hamlib Dummy (built-in test profile) | 1 | None |

So an flrig user is not a power user needing a special path — they pick
"FLRig" from the same dropdown as "FT-991," and catnector spawns
`rigctld -m 4` against it. Each Flex slice being its own hamlib model also
means "one rig profile per slice" falls out naturally.

Two secondary modes live behind an *advanced* section of the rig profile,
and most users never see them:

- **Managed, external binary** — catnector still launches rigctld, but from
  a user-specified path instead of the bundled one. Exists because hamlib
  adds radio backends continuously and someone with a brand-new radio
  shouldn't have to wait for a catnector release.
- **Attach** — catnector connects to a `rigctld` *someone else already
  started*, at a given `host:port`. Narrow but real: the operator already
  running rigctld to share the rig with WSJT-X, who wants catnector to join
  it rather than start a second one.

### 8.2 hamlib version policy

Network rig support does **not** drive the hamlib version choice — FLRig
(model 4) and NET rigctl (model 2) are long-standing backends, and Flex has
been supported for years. All of it lives inside rigctld; catnector issues
the same `f`/`F`/`m`/`M` commands whether the far end is a serial FT-991 or
a Flex on the LAN, and never grows a code path for "network rig."

What actually drives the version question:

- **New radio backends** get added to hamlib continuously. Bundle a recent
  hamlib and allow the external-binary escape hatch (§8.1).
- **NET rigctl protocol variance across versions** — the real compatibility
  surface, and it only bites where the peer's hamlib isn't ours. The known
  hazard is vfo-mode: `rigctld -o` requires a VFO argument on every command,
  so `f` and `f currVFO` are not interchangeable; `\chk_vfo` is how a client
  discovers which regime it's in. `\dump_state` has also gained fields over
  time.

**Policy: floor at hamlib 4.5; release builds bundle 4.7.x.**

**Distributions cannot be relied on to clear that floor.** Ubuntu 22.04 —
the release runner, chosen because its glibc 2.35 keeps the AppImage working
on Debian 12 and Ubuntu 22.04 — ships hamlib **4.3.1**, below our own
minimum. A bundle built from it fails catnector's own `--check-rig`. The
release workflow therefore **builds hamlib from source** rather than
installing the distribution package, which keeps the widest glibc reach and a
current hamlib at the same time. Windows takes the official upstream build,
pinned to the same version.

**Probe, never assume — in every mode, including the bundled one.** On
connect, issue `\chk_vfo` and `\dump_state`, adapt command formatting to the
answer, and refuse below the floor with a plain-language message.

Implementation confirmed how load-bearing this is: in VFO mode, sending a
command *without* the VFO argument does not return an error — **rigctld
resets the connection.** Guessing wrong costs the whole rig session, not one
command. The
bundled mode always passes this check; it runs it anyway so there is exactly
one code path, rather than a probe path whose first real test happens on a
stranger's computer. **Catnector displays the detected hamlib version** in
the UI, so support conversations start from a fact.

### 8.3 Rig setup UX is generated from hamlib capabilities

The rig picker is built from hamlib's model list (`rigctl -l` — 314 models
in 4.6.5), never raw model numbers. The *settings* form is likewise
generated from `--dump-caps` for the selected model rather than
hand-maintained. For an FT-991, hamlib already knows:

```
Port type:      RS-232
Serial speed:   4800..38400 baud, 8N2, ctrl=CTS/RTS
Write delay:    0ms, timeout 2000ms, 3 retry
Can set Frequency: Y   Can set Mode: Y   Can set VFO: Y
Can get PTT:       Y   Can set Split Freq: Y
```

So catnector can offer only the baud rates that are legal *for that rig*
with the correct framing and the rig's default preselected, pick sane
timeouts, and gray out what the rig cannot do — a better experience than
WSJT-X, which expects the operator to already know their own baud rate.
`Can get PTT` is also what makes a don't-QSY-mid-transmission guard
implementable per rig, degrading gracefully where PTT can't be read.

Model list and caps are obtained from the bundled binaries, so caps-driven
forms are available exactly where they are needed (the managed-mode config
wizard). In attach mode the rig was already chosen by whoever started
rigctld, so there is no form to generate and catnector simply probes the
live connection.

### 8.4 Threading and polling

- **The GUI thread performs no *blocking* I/O.** One QThread for rig
  poll/apply, Qt signals between it and the UI. No qasync.
- **The site connection stays on the GUI thread.** Implementation used Qt's
  `QWebSocket` and `QNetworkAccessManager`, which are event-driven and never
  block, so a second thread would add cross-thread marshalling for no
  benefit. The rig layer keeps its own thread because a serial radio
  genuinely blocks for hundreds of milliseconds; the WebSocket does not.
- **Poll rate is decoupled from report rate.** A slow CAT rig will not
  reliably answer `get_freq` inside one second; the server-configured
  interval (§6) governs *reports*, not polls. Catnector reports the last
  known good value along with its age.
- **Poll only when it matters** — connected and spotted. No reason to
  hammer someone's radio at 1 Hz while catnector sits idle in a tray.
- **Rig health is reported separately from session health** (§3). "Site
  connected, rig offline" is a real and common state — cable pulled,
  rigctld died, port permission denied — and the site must be able to show
  it rather than drop the spot or keep displaying a stale frequency as if
  it were live.

## 9. Tech decisions (settled)

**GUI toolkit: PySide6.** Chosen over Tkinter, wxPython, Flet, and
DearPyGui. Rationale: Qt is native (or native-feeling) and first-class on
Windows/Mac/Linux alike; PySide6 specifically (not PyQt6) because it's
LGPL-licensed by the Qt Company itself, which is far more comfortable for
an open-source tool than PyQt6's GPL/commercial-license split. PyInstaller
packaging for PySide6 apps is well-trodden, which matters since
catnector's users are ham operators, not developers — they need a plain
installer/binary per OS, not a Python environment to set up. Qt Designer
is available for laying out the intentionally-slim UI (rig picker, connect
button, status indicator, profile dropdowns) without hand-coding widget
positions.

**Licensing: GPLv3.** Deliberate copyleft, not MIT — the ecosystem this is
aimed at is other ham/hobby/community-run sites, not companies, so the
friction copyleft adds to commercial adoption isn't a real cost here, and
requiring shared improvements fits the community-project spirit. **GPLv3,
not AGPL:** catnector is a distributed desktop app (downloaded and run
locally), not a server — GPL's disclosure trigger (fires on distribution)
already covers "someone forks catnector and ships a modified build to
their users." AGPL's extra network-use clause exists to close the SaaS
loophole for server software that's never distributed as a binary, which
isn't catnector's situation. No conflict with PySide6 (LGPL is designed to
be safely used inside GPL applications).

**Protocol spec document (separate `catnector-protocol` repo): CC-BY
4.0**, deliberately more permissive than catnector's own code license.
Implementing a spec isn't a copyright derivative of the spec text
regardless of its license, but a permissive doc license removes any
doubt/hesitation for a site writing an independent implementation — keeps
"any site can stand up a compatible endpoint" friction-free even though
catnector's own reference code is copyleft.

### 9.1 Platform targets and code signing (settled for MVP)

**MVP ships Linux and Windows binaries. macOS is deferred to post-MVP.**

**macOS: an unsigned bundle is worse than no bundle.** On Apple Silicon a
quarantined, unsigned GUI app is hard-blocked, and macOS 15 (Sequoia)
removed the Control-click → Open bypass that used to be the folk-knowledge
workaround. What remains is: double-click, get blocked, open System Settings
→ Privacy & Security, scroll to the bottom, click "Open Anyway,"
authenticate, launch again. Six steps, in a place the user has no reason to
look, for an app that appears broken — to an audience of ham operators, not
developers. Shipping that costs more trust than shipping nothing, on a tool
whose whole proposition is "let this touch your radio." "macOS coming later"
is an honest state; "macOS, but it looks broken" is not.

When macOS does happen: **Apple Developer Program ($99/yr) and proper
notarization, or not at all.** In the meantime the interim path is
**`pipx install catnector`** (§9.2) — no downloaded bundle, therefore no
quarantine attribute and no Gatekeeper involvement at all, working from day
one for any Mac-owning ham who has Python. Building from source or a
Homebrew/MacPorts formula works the same way, and is how a good share of OSS
ham software sidesteps this problem entirely. This is reason enough to
publish to PyPI early, independent of the binary story.

**Windows: unsigned for MVP, one SmartScreen dialog accepted** ("Windows
protected your PC" → More info → Run anyway). Milder than the macOS path and
judged acceptable for MVP, possibly permanently. If revisited, note that
since mid-2023 publicly trusted code-signing certificates require the key on
FIPS-certified hardware or a cloud signing service (the cheap file-based
`.pfx` era is over), that a standard OV certificate does **not** immediately
silence SmartScreen — reputation still has to accrue, only EV gets it
instantly — and that the cheap modern option is a cloud signing service with
individual (not just organizational) eligibility. Verify pricing and
eligibility at the time; that market moves.

**Linux:** no signing surface. Nothing to decide.

**Mandatory regardless of any of the above: ad-hoc signing on macOS arm64.**
Apple Silicon refuses to execute unsigned Mach-O binaries outright — not a
prompt, an immediate kill — so `codesign -s -` is required even with no
Apple account. This matters more for catnector than for a pure-Python app
because the bundle carries **nested executables**: `rigctld` plus whatever
dylibs hamlib brings with it, each of which must be signed. The same
constraint reappears at notarization time, where the hardened runtime
requires every nested Mach-O to carry the same Developer ID signature, and
bundled hamlib libraries may need `disable-library-validation`.

**Open, pending real-world input:** the user is canvassing ham peers on how
operators actually feel in practice about the Sequoia settings dance and
about the SmartScreen dialog. Both decisions above are revisitable on that
input.

### 9.2 Development and packaging toolchain (settled)

**Three audiences, three tools — they are different layers, not competing
choices:**

| Who | How they get catnector | Tool they touch |
|---|---|---|
| Casual ham (the ~99%) | AppImage / `.exe` from Releases | none |
| Technical user | `pipx install catnector` | pipx |
| Maintainer + contributors | clone, `uv sync`, `uv run pytest` | uv |

The end user never encounters Python tooling at all — that is the entire
point of shipping frozen binaries.

**Project layout:** `src/catnector/`, PEP 621 `pyproject.toml`, no
`setup.py`.

**Dependency management: `uv`,** for the lockfile. With unpinned
requirements, two builds a month apart bundle different library versions,
and a bug report against a shipped binary becomes unreproducible — which
matters far more when freezing binaries than when shipping a script people
install fresh. Secondary: uv is a single static binary needing no Python
bootstrap, so CI setup is one action.

**This choice is deliberately reversible.** What matters is the `src/`
layout and a standard PEP 621 `pyproject.toml`; whether uv or pip reads it
is swappable. `pip install -e ".[dev]"` is documented in the README on equal
footing so no contributor is forced into a tool they don't use, and uv
produces an ordinary wheel — `pipx install catnector` behaves exactly as it
would otherwise.

**Lint/format:** ruff for both. **Tests:** pytest + pytest-qt; the rig layer
is testable headless against `rigctld -m 1`, which is where most of the
value is. **Python floor:** `>=3.10` (PySide6 6.11.2 ships `cp310-abi3`).

**Distribution formats:**
- **Linux: AppImage** — single file, no install, works across distros, and
  what Linux hams expect from desktop ham software.
- **Windows:** PyInstaller one-file `.exe`, unsigned for MVP (§9.1).
- **PyPI wheel**, so `pipx install catnector` serves the technical subset.

**hamlib is bundled**, so an operator never installs it. Only `rigctld` and
`rigctl` are staged into the bundle: PyInstaller's own analysis follows them
to `libhamlib.so.4` and the rest, placing those at the bundle root under
their sonames. Staging the libraries as well shipped every one of them twice
— about 17 MB. A spawned `rigctld` is loaded by the *system* linker, which
knows nothing about the bundle, so catnector sets `LD_LIBRARY_PATH` (or
`PATH` on Windows) for it — and only for binaries that are actually ours, so
a `rigctld` the operator installed keeps the environment they installed it
into.

`catnector --check-rig` drives a simulated radio through whichever hamlib the
build will really use. It is the release pipeline's proof that a bundle works
on a machine with no hamlib installed, and it is also the answer to "is
catnector broken, or is my cable unplugged?"

**CI:** GitHub Actions matrix over Linux and Windows, PyInstaller, with an
`--add-binary` step for the bundled `rigctld` (§8.1). No macOS leg for MVP
(§9.1).

## 10. Safety envelope on inbound control (settled)

Catnector's proposition is "let a website move your radio." That is only
acceptable if the limits are explicit. Catnector **never keys PTT** (§1) —
everything below concerns the tune itself.

`SPEC.md` §12 makes most of this binding on *any* client, not just this one:
no keying, PTT deferral, refusing out-of-range frequencies, no
licence-privilege checking, visible disclosure, and a disconnect control.
That is the floor. What follows is how catnector meets it, and where it
goes further — the announce-then-show behaviour in §10.4 and the
pending-action design of manual mode in §10.5 are product choices, not
protocol requirements.

### 10.1 PTT guard — defer, never yank

**If the rig reports PTT active, hold the QSY until it drops**, with a
timeout after which the pending tune is abandoned rather than applied late.

This is not etiquette. Retuning a VFO mid-transmission can drive an
amplifier or antenna tuner that is matched for the *old* band — a
hardware-damage argument, not a politeness one. Modern rigs largely protect
themselves here, and catnector never transmits, but "largely" and "never
ourselves" are not reasons to move a radio while it is keyed.

`Can get PTT` is reported per rig in hamlib caps (§8.3), so catnector knows
when it can enforce this and degrades gracefully on rigs that cannot report
PTT.

### 10.2 Capability clamp

**Reject any pushed frequency outside what the rig can tune**, as reported
by `--dump-caps` (§8.3). Free, automatic, per rig, no configuration. With
§10.6 empty by default, this is the only always-on limit — which is the
correct default.

**Clamped to the RX ranges, not the TX ranges.** Catnector never keys, so
refusing to *listen* somewhere the radio can physically tune would be
catnector overreaching into a decision that belongs to the operator. Whether
a frequency falls inside the rig's transmit ranges is available for display,
never enforced. Where hamlib reports no ranges at all, no limit is invented.
Ranges come from `--dump-caps` rather than a live rig's `\dump_state`
because they must be known at profile-setup time, with no radio attached.

### 10.3 Inbound rate limiting and coalescing

§6 throttles what catnector *sends*. Nothing yet throttled what it
*receives* — a buggy or hostile endpoint could spin an operator's VFO
indefinitely.

**Coalesce, don't reject.** If several updates arrive inside one window,
apply the latest and drop the intermediates; applying all of them makes the
VFO chase stale positions. Latest-wins is the right primitive.

**The ceiling is the rig, not a policy number.** A serial rig may need
100–300 ms per CAT command, so the applied rate is "no faster than this rig
can keep up," discovered at runtime, with a sane cap (~1/sec) on top. This
is deliberately independent of §6's server-configured telemetry interval,
which governs reporting and is the site's business.

### 10.4 Announcing the QSY

A radio that retunes itself must be able to say who moved it and why. The
`source` string (`SPEC.md` §7.4) is displayed whenever the rig moves.

**Announce on entry, then show state** — the distinction matters:

- **First tune of a session, or the first after an idle period:** a brief,
  configurable countdown (default ~2s) with a prominent flashing indicator
  naming the source ("Tuning to match W1ABC"), an optional sound (**default
  off** — many operators have audio in use), and the ability to apply
  immediately or cancel. Where the platform has a native idiom for this
  (tray notification, etc.), use it.
- **Continuous follow updates: applied immediately**, under a *persistent*
  "Following W1ABC" indicator rather than a per-update countdown. That
  indicator is driven by the display-only follow-state push (§3.2), not by
  the last `set_rig` — otherwise it keeps claiming a follow after the
  follow has ended.

The reason for the split: a countdown on every follow update would make
following feel laggy and broken, and would produce continuous flashing that
operators learn to ignore — an alarm that never stops is not a safety
feature. Warn once on entry; display state thereafter.

### 10.5 Manual vs auto tune

A prominent, always-visible **"manual vs auto tune"** toggle, plus one-click
disconnect. Never buried in a menu.

**Manual mode preserves the feature rather than disabling it.** An incoming
push does not vanish — it becomes a pending, clickable action ("Tune to
14.195 USB — W1ABC"). Same information, operator is the trigger. Disabling
outright would make the toggle something people flip once and forget,
discarding the point of being connected at all.

### 10.6 Operator range limits (optional, empty by default)

An operator-editable "never tune outside these ranges" list. **Optional,
empty by default, no license-class logic anywhere.**

**Catnector deliberately does not implement license privilege checking.**
Worldwide privilege data — US class sub-bands, IARU regions, per-country
allocations — is a large, drifting dataset, and a wrong answer is worse than
no answer. Catnector also never keys the radio; the licensed operator does,
and remains responsible for where they transmit. Prominent display (§10.4)
over prohibition.

## 11. MVP scope (locked)

- Ships as a Linux AppImage and a Windows `.exe`, plus a PyPI wheel for
  `pipx`; macOS deferred to post-MVP (§9.1, §9.2)
- Paste a bearer token → decodes embedded hostname → discovers the
  endpoint via `.well-known` → connects over WSS (§3.1)
- Config stored in separate INI files: site connections vs. rig profiles
  (§4)
- Only one live session per account enforced server-side; catnector shows
  a clear message if kicked by a newer session (§5)
- Rig profile setup driven by hamlib capabilities — model picker from
  hamlib's model list, settings form generated from `--dump-caps` (§8.3)
- Catnector launches and supervises `rigctld` itself; the user never
  configures rigctld separately (§8.1)
- flrig and network-native rigs (Flex, SmartSDR slices) work as ordinary
  rig-picker entries, no special path (§8.1)
- Probe the rigctld peer on connect (`\chk_vfo`, `\dump_state`), adapt, and
  refuse below the hamlib floor with a plain-language message (§8.2)
- Status indicator showing session state *and* rig state separately (§8.4)
- Reports freq/mode/rig-name/status up to the site at the throttled,
  server-adjustable interval (§6)
- Executes incoming `set_rig` pushes — one message type covering both
  one-shot tune and ongoing QSY Follow target updates (§3.2)
- Honors the forward-compatibility rules: ignore unknown fields, refuse
  (never partially apply) a message carrying an unsupported `req` field,
  advertise capabilities at handshake (`SPEC.md` §8)
- Multiple site connections + multiple rig profiles supported, one of each
  active via dropdown, clearly displayed (§3.3)
- Safety envelope on inbound control: PTT deferral, capability clamp,
  inbound coalescing, QSY announcement, manual/auto toggle (§10)
- Built-in Hamlib Dummy rig profile; development and CI run against it and
  the reference mock server, no radio required (§3.4)

## 12. Comparable / Reference

- **Hamlib** — the CAT control library catnector drives, via its `rigctld`
  network protocol rather than in-process bindings (§8)
- **flrig** — widely used rig-sharing proxy; reached as an ordinary hamlib
  backend (model 4), not as a special case (§8.1)
- **WSJT-X** — the UX benchmark for rig setup: the user configures their
  radio inside the application, and never has to know rigctld exists

## 13. Future ideas (not scoped)

### 13.1 Single-operator simultaneous multi-rig follow (SO2R-style)
The case of **one person, one login, genuinely operating two rigs at the
same time**, wanting an independent QSY Follow on each — analogous to
contest "Single Operator Two Radios" (SO2R) operating. Distinct from the
club Field Day case (already solved server-side via one-account-per-
station). Would require loosening the one-session-per-account rule (§5) to
one-session-per-(account, connection), and giving the server's
FollowSession/live-status tracking a session identifier as a first-class
dimension, not just user ID. Real feature work, not a small extension —
revisit only if there's real demand for it.

### 13.2 macOS support
Deferred from MVP, not abandoned — see §9.1 for why an unsigned macOS
bundle is judged worse than no macOS bundle, and what shipping one properly
costs (Apple Developer Program, notarization, hardened runtime across the
bundled `rigctld` and hamlib dylibs).

### 13.3 Split-aware follow
Following a DX station working **split** is the most obviously valuable
deferred feature: follow only the target's RX frequency and you land the
follower on top of the DX station they were trying to work. The protocol
reserves a `split` field and the `req` mechanism (`SPEC.md` §8.2) exists so
this can ship later without mis-tuning older installs. MVP transmits no
split information and applies freq/mode to the current VFO only.

### 13.4 Control handoff on QRT
When a followed operator wants to go QRT (stop operating), an idea for
letting them pass control of their spot — and by extension, whatever
catnector session is driving it — to a different operator, rather than
the spot just dying and stranding followers. Presumably relevant for
club/multi-operator stations. Not fleshed out — mechanism, permissions,
and how catnector would participate in a handoff are all TBD.

## 14. Next steps

- Draft the actual protocol spec document in the separate
  `catnector-protocol` repo (CC-BY 4.0), now that the responsibilities
  above are settled from real (HamQSY) implementation needs. That repo also
  carries the reference mock server and the conformance checker (§3.4).
- Scaffold the PySide6 app: rig connect + token auth + one-shot "tune my
  rig" (QSY Follow depends on this working first).
- Canvass ham peers on the real-world tolerance for the macOS Gatekeeper
  settings dance and the Windows SmartScreen dialog, and revisit §9.1 if
  the answers warrant it.
- Design the serial-permission onboarding path (Linux `dialout`/udev,
  Windows CP210x/FTDI/CH340 drivers) — flagged, not yet designed.

## 15. Milestones

| | Milestone | Deliverable | Needs `catnector-protocol`? |
|---|---|---|---|
| **M0** ✅ | Repo scaffold | **Done.** `src/` layout, pyproject + `uv.lock`, ruff (lint + format), pytest, GitHub Actions across {Linux, Windows} × {3.10, 3.13}, `catnector --version`. Nothing user-visible — it exists so every later milestone lands on green CI. | no |
| **M1** ✅ | Rig layer, headless | **Done.** `RigBackend` + `NetRigctlBackend`, `RigctldProcess` spawn/supervise on an ephemeral port, peer probe (`\chk_vfo`, `\dump_state`, hamlib floor 4.5), model list and `--dump-caps` parsing. 35 tests against `rigctld -m 1`. No GUI. | no |
| **M2** ✅ | GUI + rig profiles | **Done.** PySide6 shell with rig picker, connect/disconnect and live freq/mode readout; caps-generated profile editor; `rigs.ini` CRUD; built-in Hamlib Dummy profile; reveal-config-folder; serial-permission diagnosis. Rig I/O on a `QThread`, never the GUI thread. 64 tests. **First milestone worth showing another ham.** | no |
| **M3** ✅ | Site connection | **Done.** Token paste → `.well-known` → WSS connect over Qt's `QWebSocket`, `hello`/`welcome`, heartbeat, close-code policy with the kick modal, `req` refusal, display-only `follow_state`, `sites.ini` at 0600. 96 tests, the site ones run against the reference mock site. | **yes** |
| **M4** ✅ | Telemetry + control | **Done.** Throttled, change-driven reports carrying freq/mode/passband/rig name/rig health with a read timestamp; inbound `set_rig` through the full §10 envelope — PTT deferral, capability clamp, coalescing, announce-then-show, manual mode, optional operator ranges. 134 tests. **This is the MVP (§11).** | **yes** |
| **M5** ✅ | Packaging | **Done.** PyInstaller spec (one-directory on Linux, one-file on Windows), hamlib bundled with its libraries reachable at runtime, AppImage build script, release workflow across Linux/Windows/wheel, generated icon, `INSTALL.md`, and `catnector --check-rig` — which is what proves a bundle ships working rig control. | no |

PySide6 is declared as a dependency from M0 rather than M2, so that CI
proves it installs cleanly on both platforms and both Python versions before
any code depends on it — which is the whole point of the milestone.

**Sequencing: M0–M2 need nothing from `catnector-protocol`.** That repo's
spec, reference server and conformance checker (§3.4) only have to land
before M3, so client work here and spec work there can proceed in parallel.
Doing M1 and M2 first is likely to *improve* the spec — the client will have
demonstrated what it actually needs to say before the wire format is
frozen.

Serial-permission onboarding (Linux `dialout`/udev, Windows
CP210x/FTDI/CH340 drivers) belongs to M2: the rig setup flow should detect
"permission denied" and tell the operator exactly what to run, rather than
surfacing a raw hamlib error.
