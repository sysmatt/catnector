# Catnector — Project Planning

Status: design settled during HamQSY's planning phase; not yet scoped into
milestones as its own repo. This doc was extracted from `hamqsy`'s
`docs/PLANNING.md` on 2026-09-03 — see that repo for the web app's side of
the same protocol/integration (their doc kept its own copy of the shared
protocol/auth/data-model content; nothing was deleted there).

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

**One site session / one active follow at a time, per account (settled).**
Not per-rig, per-account. Multi-station scenarios (e.g. club Field Day
operations) don't need more than this — the correct mapping there is one
account per physical station/computer, not one account trying to drive
several rigs at once. True single-operator simultaneous-multi-rig
following (SO2R-style solo dual-rig operating) is a different, harder
feature — see §11 (Future Ideas).

## 3. Catnector ↔ site protocol (open, built for real needs first)

Catnector's protocol is **open**, but scope is: build what HamQSY needs
today, document it well enough that it's usable, and let it be open for
others to adopt — not a generalized/negotiated multi-vendor spec designed
up front. (The actual protocol spec document lives in the separate
`catnector-protocol` repo, CC-BY 4.0 — see §8. This section is catnector's
own implementation-facing description of what it needs to speak.)

Catnector itself doesn't know or care which "flavor" of site it's talking
to — it just speaks the protocol to whatever endpoint URL + token the user
configured.

**Endpoint responsibilities the protocol needs to cover** (grown from real
need, not speculative):
- Bearer token auth handshake (token encodes the endpoint hostname — see
  §3.1)
- Push: "set freq/mode to X" (one-shot tune)
- Push: "target now at freq/mode Y" (QSY Follow — only relevant when the
  target is itself a catnector-connected, followable spot)
- Report: "my rig is now at freq/mode Z" (keeps the user's spot accurate
  live on the site)
- Report: "my active rig profile is named W" (so the site can display
  which rig the user currently has selected, not just its freq/mode)
- Report: connect/disconnect status (so the site can show
  connected/disconnected clearly)
- Handshake: **endpoint tells catnector its desired telemetry interval**
  (see §6 — server-configurable, catnector defaults to 1s if unspecified)

### 3.1 Auth model (settled)

**Catnector ↔ site (API/WebSocket): bearer tokens** (HamQSY's server
implements these via Laravel Sanctum; catnector itself just needs to speak
plain bearer-token HTTP/WebSocket auth, nothing Laravel-specific).

- The **token itself embeds the API endpoint hostname**, so catnector is
  fully self-configuring from a single pasted token — no separate "enter
  the server URL" step. This is what makes the protocol genuinely
  federated: any site issues its own tokens carrying its own hostname;
  catnector needs zero site-specific configuration to talk to a different
  site.
- Catnector supports **multiple registered site connections** at once
  (e.g. a HamQSY token and some other site's token, both saved), but
  **only one is active at a time**, chosen via a pulldown.
- Catnector's UI must clearly display, for the active connection: **which
  site/endpoint** it's talking to, and **which username/callsign** it's
  authenticated as.
- Independently, catnector supports **multiple rig profiles**, selectable
  regardless of which site connection is active — the two choices (which
  site, which rig) are orthogonal.

**Callsign identity is trusted, not verified**, on the server side — no
QRZ/LoTW check, no postcard flow. Relevant to catnector only in that it
means callsigns aren't guaranteed unique per account server-side, and
catnector should display whatever callsign the active token/session
resolves to without assuming any uniqueness guarantee.

## 4. Config file format (settled)

**Site connections (bearer tokens) and rig profiles live in separate INI
files**, not one combined config blob. Rationale: ham operators skew
tech-savvy and comfortable editing plain-text config — separate files make
it obvious and low-friction to copy just the piece you want to another
computer (e.g. copy only the rig-profiles file to a laptop that has no
site tokens yet, or only the site-tokens file to a second machine that
already has its own rig set up). Plain, human-readable/editable config is
a deliberate choice for this audience, not an oversight.

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

## 6. Telemetry rate limiting (settled)

**Throttled to 1 update/second by default.** Fast enough to read as "live"
to a human, but keeps servers from being flooded as someone spins a VFO.
Two important details:
- **Enforced client-side, in catnector itself** — not just relying on
  server-side rejection — so catnector never spams the API in the first
  place, rather than firing requests that get dropped.
- **Server-configurable:** the interval is a default (1s) catnector ships
  with, but the API endpoint can tell catnector, as part of the connection
  handshake, what interval it actually wants — so a given site's load
  characteristics or a future "premium" faster-tier can adjust it without
  a catnector release.

## 7. Data model (catnector-local, not server-side)

- **RigProfile** — rig model, port, hamlib settings, nickname. Independent
  of which site connection is active.
- **SiteConnection** — endpoint hostname (decoded from token), bearer
  token, nickname. User can register several, only one active at a time.

(The server-side data model — User, Callsign, QTH, Spot, FollowSession —
lives in the implementing site's own planning doc, e.g. `hamqsy`'s
`docs/PLANNING.md` §3.2. Catnector doesn't store or need to know that
schema directly, only the protocol messages in §3 above.)

## 8. Tech decisions (settled)

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

## 9. MVP scope (locked)

- Paste a bearer token → decodes embedded hostname → connects (§3.1)
- Config stored in separate INI files: site connections vs. rig profiles
  (§4)
- Only one live session per account enforced server-side; catnector shows
  a clear message if kicked by a newer session (§5)
- Rig profile setup (hamlib model/port), status indicator
  (connected/disconnected)
- Reports freq/mode/rig-name/status up to the site at the throttled,
  server-adjustable interval (§6)
- Executes incoming "set freq/mode to X" pushes — both one-shot tune and
  ongoing QSY Follow target updates
- Multiple site connections + multiple rig profiles supported, one of each
  active via dropdown, clearly displayed (§3.1)

## 10. Comparable / Reference

- **Hamlib** — the CAT control library catnector wraps

## 11. Future ideas (not scoped)

### 11.1 Single-operator simultaneous multi-rig follow (SO2R-style)
The case of **one person, one login, genuinely operating two rigs at the
same time**, wanting an independent QSY Follow on each — analogous to
contest "Single Operator Two Radios" (SO2R) operating. Distinct from the
club Field Day case (already solved server-side via one-account-per-
station). Would require loosening the one-session-per-account rule (§5) to
one-session-per-(account, connection), and giving the server's
FollowSession/live-status tracking a session identifier as a first-class
dimension, not just user ID. Real feature work, not a small extension —
revisit only if there's real demand for it.

### 11.2 Control handoff on QRT
When a followed operator wants to go QRT (stop operating), an idea for
letting them pass control of their spot — and by extension, whatever
catnector session is driving it — to a different operator, rather than
the spot just dying and stranding followers. Presumably relevant for
club/multi-operator stations. Not fleshed out — mechanism, permissions,
and how catnector would participate in a handoff are all TBD.

## 12. Next steps

- Draft the actual protocol spec document in the separate
  `catnector-protocol` repo (CC-BY 4.0), now that the responsibilities
  above are settled from real (HamQSY) implementation needs.
- Scaffold the PySide6 app: rig connect + token auth + one-shot "tune my
  rig" (QSY Follow depends on this working first).
- Decide on the Hamlib Python binding approach (direct `Hamlib` Python
  bindings vs. shelling out to `rigctld`) — not yet discussed/decided.
