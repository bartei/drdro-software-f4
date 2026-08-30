# v1.5 Board Integration — design

> Verbose design for adding **drDRO mainboard v1.5** support to the standalone
> `drdro-software-f4` repo **without breaking the current (v1.0) board**. Phased tracker:
> `v15_todo.md`. Read alongside `migration_design.md` (the RCP→line-protocol port) and the
> firmware truth in `../drdro-mainboard/firmware/shared/Settings.h`.

## Goal

Let `drdro-software-f4` drive **both** board revisions from one codebase:

- **v1.0** — the existing STM32F411 board, RS-485 line protocol, 4 encoder scales. Must keep
  working *exactly* as today (connection, poll rate, firmware update, UX all unchanged).
- **v1.5** — the new mainboard (`../drdro-mainboard`): same STM32F411 **line protocol**, but it
  adds a **W5500 Ethernet** controller exposing the same CLI over **TCP :5555**, and grows to
  **5 encoder scales** (plus analog outputs, board network config, and other new settings vars).

The protocol is backwards-compatible: same framed `key=value`/`crc=HH` wire format, same
commands. v1.5 only adds a new **transport** (TCP) and **more variables**. Support is therefore
additive.

## Background — where the v1.5 code comes from (repo topology)

The v1.5 work exists as a **POC inside a monorepo**: `../drdro-mainboard/software`. That monorepo
(`bartei/drdro-mainboard`) versions firmware + software together under **one** semantic-release
tag and was deliberately designed to *replace* the standalone repos. The POC forked from
`drdro-software-f4` at **~v1.7.0**, so its copies of shared files predate our later `dev`/`main`
fixes (line-noise hardening `96050a5`, ELS thread direction, nmcli graceful degradation). This is
a **three-way** situation:

```
                cafd067 (~v1.7.0 shared base)
               /                        \
   our dev/main (v1.7.x/1.8.0-beta.1)     POC monorepo (v1.5 board work, Aug 2026)
   + line-noise fix, ELS direction,       + TCP transport, discovery, connection screen,
     nmcli degradation, update fixes         dynamic scale count, monorepo update system
```

**Consequence:** we cannot copy files wholesale — the POC would revert our newer work and drop
our hardening. Integration is selective (cherry-pick / port / ignore), never a file overwrite.

## Scope decision — Half 1 only (CONFIRMED)

The POC's changes split into two separable halves. We are porting **Half 1 only**.

- **Half 1 — runtime board support (PORT):** TCP transport, network discovery, a Connection
  setup screen, runtime transport switching, dynamic 4/5-axis scale count, responsive home bars.
  All of it is additive and backwards-compatible; the v1.0 serial path is untouched.
- **Half 2 — monorepo update-system rewrite (DEFER / OUT OF SCOPE):** `release.py`,
  `stack_update.py`, `pending_update.py`, `firmware_apply.py`, `version.py`, and rewrites of
  `update_screen`/`firmware_screen`/`fw_update_banner`/`fw_compat.py`. The POC deliberately made
  this **not backwards-compatible**: single-version exact-match, repoint at `bartei/drdro-mainboard`,
  `/opt/drdro` appliance paths, delete `COMPANION_FW_VERSION`. Its own design doc
  (`../drdro-mainboard/docs/update_system_todo.md`, Goal 6) states *"no backwards compatibility,
  no version-regression concerns."* Adopting it here would break this repo's independent release
  model and every fielded v1.0 board's update path — the direct opposite of the mandate.

  **Rationale for deferring:** the user requirement is *integrate v1.5 without breaking the current
  software*. Half 2 cannot satisfy that without being re-architected behind a board-type switch
  (routing v1.0→`drdro-firmware-f4`, v1.5→`drdro-mainboard`), which is a separate, larger project.
  Half 1 delivers a *usable* v1.5 board (connect, correct axis count, live DRO) on its own.

## v1.5 facts that drive the design (verified from firmware source)

- **Same line protocol over a new pipe.** `firmware/.../NetCli.c` serves the identical
  `key=value`+`crc=HH` framing over **TCP :5555** (firmware-update data on :5556). Nothing about
  the request/response format changes. (`tcp_transport.py` docstring confirms: "the only thing
  that differs is the byte pipe.")
- **Settings magic bumped DRO1 → "DRO2"** (`Settings.h`): a v1.5 image and a v1.0 image are
  mutually unparseable, but that is a *firmware/flash* concern, not a protocol-wire concern.
- **Scale count is board-specific:** v1.0 = 4, v1.5 = 5. The board reports its count via a new
  read-only `scales.count` variable. Software must treat scale count as **dynamic**, not a
  compile-time constant.
- **New settings variables** (v1.5 only): `scale_dir[5]`, `servo_index`, `aout_raw[2]` (0–10 V VFD
  DACs), `net_dhcp/net_ip/net_mask/net_gw/net_port`, `din_debounce_ms`, `com_baud`. See Non-goals.

## Chosen approach

### A. Transport abstraction — duck-typed, config-selected

`TcpTransport` (new, stdlib `socket`) mimics the slice of `serial.Serial` the client uses
(`read/write/flush/reset_input_buffer/close`), so it drops into the same byte-pipe hole. The
client picks transport on **`host is None` (serial) vs `host` set (tcp)**; no protocol change.

- **Port `tcp_transport.py` and `discovery.py` as new files** — zero effect on the serial path.
  `discovery.py` is a stdlib `asyncio` TCP connect-scan of the local /24 that sends `version`
  and keeps the boards that answer with a valid frame. Off-subnet boards are entered by IP.
- **Cherry-pick, never overwrite `protocol_client.py`.** Add only the TCP plumbing
  (`host`/`tcp_port`/`connect_timeout` ctor params, `kind`/`description`/`is_open` properties,
  `_open_transport` with an unchanged serial branch, `_reset_transport`/`_safe_close`, broaden
  `except serial.SerialException` → `except (serial.SerialException, OSError)`) **onto our
  hardened file**. The POC's file predates `96050a5` and removed the `ValueError`/
  `UnicodeEncodeError`/`isascii` guards — those MUST be preserved (see D3).

### B. Connection selection & config — default **serial**

`app.py.build()` reads a `[device]` transport block and constructs `Board` accordingly. New
`connection_screen.{py,kv}` (registered in `manager.py`, reached from a new "Connection" button
in `setup_screen.kv`) lets the user pick serial vs TCP, scan for boards, and **apply live** via
`board.reconfigure()` + `board.set_poll_period()` — no app restart.

**Config keys** (`config.ini` `[device]`): `transport` (`serial`|`tcp`), `host`, `tcp_port`
(5555), `serial_port`, `baudrate`, `refresh_hz`. **Default `transport=serial`** (D2), and if
`transport` is absent but `serial_port` is present, treat as serial — so an existing v1.0 install
keeps opening its serial port instead of sitting idle on a blank-host TCP.

### C. Dynamic scale count — board-reported, default 4

`board.py` gains a `scale_count` `NumericProperty` seeded from `SCALES_COUNT` and updated from the
board's `scales.count` on connect via `_apply_scale_count(n)`, which grows/shrinks the `inputs`
`ListProperty` (firing Kivy observers that resync `app.inputs`/`app.scales`). **`SCALES_COUNT`
stays 4** (D4): a v1.0 board that doesn't know `scales.count` then keeps 4 axes; a v1.5 board
reports 5 and the list grows. The responsive home-bar layout (spacer + `Window`-relative caps)
keeps few/many coordbars proportioned and pins them to the top.

### D. board.py lifecycle — lazy-open/retry + runtime reconfigure

Adopt the POC's lazy-open-in-loop + 1 s backoff (`_handle_link_error`) and `reconfigure()`/
`set_poll_period()`. This makes an absent board at startup a retry instead of a fatal abort —
strictly better for both board types — and enables serial↔TCP switching without a restart.

## Decisions (with rationale + rejected options)

- **D1 — Scope = Half 1 (runtime) only.** *Rejected:* full monorepo port (breaks v1.0 update +
  standalone releases); dual board-type-switched update system (large; not needed for a usable
  v1.5 board). See "Scope decision".
- **D2 — Default `transport=serial`; migrate absent-key installs to serial.** The POC defaults
  `tcp` with a blank host → a fresh v1.0 install would never open the serial port. *Rejected:*
  POC's tcp-default (a v1.0 regression).
- **D3 — Cherry-pick TCP onto the hardened `protocol_client.py`; never overwrite.** Preserves the
  `96050a5` line-noise guards (`as_int/as_float/as_ints/as_floats` `ValueError` guard,
  `parse_response` `UnicodeEncodeError` guard, `command()` `isascii` check). *Rejected:* copy the
  POC file (reintroduces crash paths on noisy RS-485).
- **D4 — `SCALES_COUNT` stays 4; scale count is dynamic via `scales.count`.** Avoids a phantom 5th
  axis on a v1.0 board that doesn't report the var. *Rejected:* POC's `SCALES_COUNT=5` default.
- **D5 — Keep the existing update/firmware/`fw_compat` system unchanged.** v1.0 boards keep the
  `COMPANION_FW_VERSION` gate and the `drdro-firmware-f4`/`drdro-software-f4` update paths. Do
  **not** import `version.py`/`release.py`/`stack_update.py`/`pending_update.py`. (Follows D1.)
- **D6 — Do not port the "ignore" files.** `platform.py`, `network_screen.{py,kv}`,
  `ssid_popup.py`, `elsbar.{py,kv}`, `main.py` — our `dev` branch is newer; porting reverts
  committed work (nmcli graceful degradation, ELS thread direction; `main.py` diff is CRLF-only).
- **D7 — TCP is the poll/protocol transport only; firmware flashing stays serial.** Bootloader +
  YMODEM over TCP is unproven, and Half 2 is out of scope. *Known limitation:* a v1.5 board
  connected over TCP cannot use the manual firmware screen (which flashes over the board pipe);
  flash such a board over serial. Documented, not solved, this phase.
- **D8 — New v1.5 settings vars get no UI this phase** (`scale_dir`, `servo_index`, `aout`,
  `net.*`, `com_baud`, `din_debounce`). The board runs on its firmware defaults (DHCP on, etc.).
  The POC ships no UI for them either. Deferred to a follow-on. (See Non-goals.)

## Files touched

**New (port from POC, adapt imports):**
- `dro/comms/tcp_transport.py`
- `dro/comms/discovery.py`
- `dro/components/screens/connection_screen.py`, `connection_screen.kv`

**Cherry-pick / edit (preserve our newer code):**
- `dro/comms/protocol_client.py` — add TCP plumbing onto the hardened file (D3).
- `dro/dispatchers/board.py` — `transport/host/tcp_port` kwargs, `reconfigure()`,
  `set_poll_period()`, lazy-open/retry loop, `_handle_link_error`, `scale_count` +
  `_apply_scale_count()`, `inputs` bindable. Keep the serial poll path intact.
- `dro/utils/constants.py` — comment only; `SCALES_COUNT` stays 4 (D4).
- `dro/app.py` — `[device]` transport block, **default serial** (D2); `_sync_input_aliases` +
  `board.bind(inputs=…)`. **Skip** the POC's `update_status`/`_start_pending_update`/
  `installed_version()` swap (Half 2).
- `dro/components/manager.py` — register `ConnectionScreen`.
- `dro/components/screens/setup_screen.kv` — add "Connection" button; **keep** the "Firmware"
  button (D5/D7).
- `dro/components/home/coordbar.kv`, `dro_coordbar.kv`, `dro_mode_layout.py`,
  `index_mode_layout.py` — responsive layout for variable coordbar count.

**Ignore (do NOT port — D6):** `dro/utils/platform.py`, `dro/components/screens/network_screen.{py,kv}`,
`dro/components/popups/ssid_popup.py`, `dro/components/home/elsbar.{py,kv}`, `dro/main.py`.

**Untouched (Half 2 — D5):** `dro/comms/updater.py`, `dro/comms/ymodem.py`, `dro/utils/fw_compat.py`,
`dro/components/screens/update_screen.{py,kv}`, `dro/components/screens/firmware_screen.{py,kv}`,
`dro/components/home/fw_update_banner.{py,kv}`.

## Deploy commands + blast radius

```bash
uv sync
uv run pytest            # unit suite (currently 97 green) + new transport/discovery/scale-count tests
uv run python -m dro.main
```

**Blast radius:** `board.py` is the driver core polled by every screen — the highest-risk edit.
The serial poll loop, poll rate, and connect lifecycle for **v1.0** must be verified unchanged.
`protocol_client.py` is on the hot path for every command; the cherry-pick must not disturb the
serial branch or the line-noise guards. `app.py`/`manager.py`/`setup_screen.kv` change startup and
navigation; the default-serial migration (D2) is the key back-compat guard. Everything else is
additive UI. No dependency changes (`pyproject.toml` untouched — TCP is stdlib).

## Verification (numbered)

1. `uv run pytest` green — existing 97 plus new tests below.
2. **Fresh start, no `[device].transport`** → app constructs a **serial** Board (assert in a unit
   test of the app-config resolution / `build()` transport selection). No TCP-blank-host idle.
3. **v1.0 serial poll unchanged** — with a serial config, the poll loop opens the port and
   `comm_rate > 0` at the configured Hz (headless client stand-in / existing board tests still pass).
4. **Line-noise hardening intact** — `Response.as_int/as_float/as_ints/as_floats` return `None`/`[]`
   (not raise) on garbled values; `parse_response` tolerates non-ASCII; `command()` rejects
   non-ASCII. Keep/extend the `96050a5` tests.
5. **`TcpTransport`** unit tests — buffered `read`, `b""` on timeout, `ConnectionError` on server
   close, `TCP_NODELAY` set (use a stdlib loopback `socket` server; no hardware).
6. **`discovery`** unit tests — `probe` returns `{host,port,version}` on a valid framed `version`
   reply and `None` otherwise; `local_scan_hosts` excludes own addresses (inject a fake local IP).
7. **`board.reconfigure`** swaps serial↔tcp and the loop reopens the new pipe (unit test with a
   fake ProtocolClient).
8. **Dynamic scale count** — `scales.count=5` grows `inputs`/`scale_count` to 5; `=4` shrinks to 4;
   absent/`error` leaves the default 4. `app.inputs`/`app.scales` stay in sync.
9. **Connection screen** — KV parses and instantiates headless; `apply()` persists all six
   `[device]` keys; "TCP selected, no host" warns instead of crashing.
10. **Home bars** — KV parses; `dro_mode_layout`/`index_mode_layout` build with 1 and with 5
    coordbars without exceptions (spacer present, servobar stays last in index mode).
11. **Half 2 untouched** — `update_screen`/`firmware_screen`/`fw_update_banner`/`fw_compat.py`
    unchanged; no import of `version.py`/`release.py`/`stack_update.py`/`pending_update.py`
    anywhere (grep clean).
12. **Ignore-list intact** — `git diff` shows no changes to `platform.py`, `network_screen.*`,
    `ssid_popup.py`, `elsbar.*`, `main.py`.

> **Verification is via pytest + KV parse/instantiate stand-ins, not screenshots** — this
> environment cannot render/screenshot the Kivy app (headless GL blocked; see the project memory).
> A real bench check on a v1.0 board (serial still works) and a v1.5 board (TCP connect, 5 axes,
> discovery) is the final HW gate, done by the user.

## Non-goals / deferred

- **Half 2 — the monorepo update system** (single-version stack update, `release.py` et al.).
  Revisit only if this repo adopts the monorepo release model or a board-type-switched updater.
- **UI for new v1.5 settings vars** — analog outputs (`aout`), board network config (`net.*`,
  DHCP/static), `scale_dir` direction flip, `servo_index`, `com_baud`, `din_debounce_ms`. Board
  uses firmware defaults until a follow-on phase adds screens/items.
- **Firmware flashing a v1.5 board over TCP** (D7) — flash over serial for now.
