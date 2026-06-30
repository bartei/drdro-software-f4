# RESUME — drDRO Software (drdro-software-f4)

> Pick-up doc for a fresh Claude Code session. Current state, what's decided, what's open,
> next steps, commands, gotchas. **Full design is in `docs/migration_design.md`; phased work
> in `docs/migration_todo.md`.** Read those two before touching code.

## What this project is

The host-side successor to **rotary-controller-python (RCP)**: a Kivy DRO / single-axis
controller UI for the **drDRO** STM32F411 board. Mandate for this repo:
1. **Port RCP 1:1** (every screen/feature — Kivy UI unchanged).
2. **Replace the driver layer** — RS-485 **Modbus RTU** (`minimalmodbus`) → the firmware's
   **custom CLI line protocol** (`pyserial`).
3. **Add firmware update + bank management** over the same RS-485 bus (YMODEM).
4. **Move static config to the board's flash settings** instead of re-pushing on every reconnect.

The firmware side (`../drdro-firmware-f4`) is **already shipped & HW-verified** (protocol +
dual-bank IAP bootloader + persistent settings, ≥ v0.2.2). We are building the host that
talks to it.

## Current state (2026-06-29)

- ✅ Repo initialized: uv project, branch `main`, package `dro`, `pyserial`. Design docs +
  decisions confirmed (D2–D6); see `docs/migration_design.md` / `migration_todo.md`.
- ✅ **Firmware Phase 0b (HW-verified):** `sta` extended with `servo.tgt`+`servo.mode` on branch
  `feat/sta-servo-fields` in `../drdro-firmware-f4` (commit `0a1e6b3`). **Flashed to the board.**
  ⚑ Not yet merged to firmware `main`/`dev`.
- ✅ **Phase 1 (HW-verified):** `dro/comms/protocol_client.py` — async, lock-guarded line-protocol
  client (framed req/resp, CRC verify, glitch retry, `*HH`). 15 unit tests.
- ✅ **Phase 2 + 3 (HW-verified):** dispatchers re-pointed to the protocol —
  `board.py` (poll loop + sync↔async bridge + `map_sta` + settings cache + debounced save),
  `servo/axis/input/els`, plus ported `ctype_calc/saving_dispatcher/formats/axis_transform`.
  Firmware = source of truth for `servo.max/acc/jog` (read on connect); ratios pushed live,
  never saved. 4 unit tests + a headless HW harness drove the live board successfully.
- ✅ **Phase 4 (built & rendering):** full Kivy UI ported into `dro/` (19 screens + 51 `.kv`,
  home modes/bars, popups, widgets, plot, toolbars) + app shell (`app.py`/`main.py`/`manager.py`/
  `appsettings.py`/`feeds.py`) + pattern dispatchers + assets. App builds headless (Xvfb+SDL2/GL),
  all 19 screens instantiate, the home screen renders live against the board (v0.1.0).
- ✅ **Phase 4 interactive parity (real desktop, DISPLAY :0):** all 24 screens toured + render,
  4 home modes, keypad; servo values read live from flash. Fixed a servo-mode oscillation bug
  (async write reverted by laggy `sta` read) — `_expected_mode` guard (commit e1a1dc5).
- ✅ **Live motion (HW-verified via UI):** servo jog ramps pos; index counts `stepsToGo`→0 and
  completes. Confirmed firmware motion is solid via a direct-client probe too.
- ✅ **Phase 5 (HW-verified):** `dro/comms/ymodem.py` + `updater.py` (GitHub release list/download +
  dual-bank flash flow) + `ProtocolClient.run_blocking` + `Board.pause/resume`; firmware screen
  (version, active bank, boot-bank selector, manual reset, GitHub version list, install, progress
  bar, status log). Flashed a local `.bin` into the inactive bank over RS-485 and booted it
  (bank 1→0, version updated). **GitHub fetch path untested here (no network/CA certs).**
- ⏳ **Next: Phase 6 (release & polish)** — CI (GitHub Actions build+tests, semantic-release),
  verify GitHub firmware fetch on a networked machine, RCP dead-code cleanup, Modbus→protocol
  user notes. Optional: expose rollback/erase/crc in the firmware UI (plumbing exists).

### Running the UI
- `uv run python -m dro.main` (config: `config.ini` at repo root; serial port set there).
- The board poll loop is **asyncio** (not Kivy Clock); `MainApp.build` calls `board.start()` after
  the loop is up (under `async_run`). `board._spawn` schedules writes on that loop.
- **NixOS headless GL recipe** (Xvfb): the uv-wheel SDL2 needs system GL/X libs on `LD_LIBRARY_PATH`.
  Find real `.so` dirs (NOT `-dev` outputs) for `libGL.so.1` (libglvnd) + `libX11/Xext/Xrender/
  Xcursor/Xi/Xrandr/Xinerama`, then:
  `nix-shell -p xvfb-run mesa --run "xvfb-run -a -s '-screen 0 1024x600x24' env LD_LIBRARY_PATH=<dirs> LIBGL_ALWAYS_SOFTWARE=1 uv run python -m dro.main"`.
  On a real desktop with system GL this is unnecessary — just `DISPLAY=:0 uv run python -m dro.main`.
  Scratchpad has `run_app.py` (screenshot-then-quit) + `gldirs.txt` (the resolved lib dirs).
- ST-Link flashing leaves the board in ST ROM (HW-1 floating BOOT0). Recover with an openocd
  `reset run` (`-f interface/stlink.cfg -f target/stm32f4x.cfg -c "init; reset run; exit"`).
- Host config dir is `~/.config/drdro-software` (was `rotary-controller-python`). No Modbus address.

## Source repos (read-only references)

- `../rotary-controller-python` — the app being ported. Driver layer to replace:
  `rcp/utils/{communication,base_device,devices,ctype_calc}.py`. State in
  `rcp/dispatchers/{board,axis,input,servo,els,formats,...}.py`. UI in `rcp/components/**`.
  `rcp/CLAUDE.md` holds the coding standards (carried over). `rcp/todo.md` lists open items —
  note *"STM32 firmware flashing from Pi"* is this project's Part E.
- `../drdro-firmware-f4` — the firmware. **Protocol truth:**
  `docs/protocol_design.md`, `docs/dualbank_design.md`, `shared/Settings.h`,
  `shared/Bootloader.h`, and the working host updater **`tools/dro_update.py`** (port its
  framed-CLI reader + YMODEM sender). `app/test/test_protocol/` has exact wire-format tests.
- `../rcp-v2` — a *separate* NiceGUI/web experiment. **Not in scope**; ignore.

## Authoritative protocol facts (verified from firmware source, not just the design doc)

**Wire format:** single device, no addressing, 115200, RS-485 auto-direction (host does
nothing for direction). Request `cmd [args] [*HH]\n` (`*HH` = optional uppercase-hex XOR-8,
validated if present). Response: `key=value\n` body lines, then `crc=HH\n` (XOR-8 of body),
then a **blank line** terminator. `error=<reason>` line ⇒ failure. Arrays = one comma-joined
line. A lone `\n` repeats the last command.

**App commands:** `sta set get settings save load bank rollback version help update reset`.
**`sta` returns ONLY:** `scales.pos`, `scales.speed`, `servo.pos`, `servo.speed`.

**Variable registry (real names → firmware fields):**
| var | type | n | RW | field |
|---|---|---|---|---|
| `scales.pos` | i32 | 4 | RW | `scales[i].position` |
| `scales.speed` | i32 | 4 | RO | `scales[i].speed` |
| `scales.num` | i32 | 4 | RW | `scales[i].syncRatioNum` |
| `scales.den` | i32 | 4 | RW | `scales[i].syncRatioDen` |
| `scales.sync` | u16 | 4 | RW | `scales[i].syncEnable` |
| `servo.max` | f32 | 1 | RW | `servo.maxSpeed` |
| `servo.acc` | f32 | 1 | RW | `servo.acceleration` |
| `servo.jog` | f32 | 1 | RW | `servo.jogSpeed` |
| `servo.mode` | u16 | 1 | RW | `fastData.servoMode` (0=off,1=sync/index,2=jog) |
| `servo.pos` | u32 | 1 | RO | `servo.currentSteps` |
| `servo.speed` | f32 | 1 | RO | `servo.currentSpeed` |
| `servo.tgt` | i32 | 1 | RW | `servo.stepsToGo` (write = start indexed move) |
| `diag.cycles` | u32 | 1 | RO | `fastData.cycles` |
| `diag.interval` | u32 | 1 | RO | `fastData.executionInterval` |

**RCP→protocol naming:** `servoEnable` (already 0/1/2) → `servo.mode`; servo `direction` →
`servo.tgt`. `ctype_calc.uint32_subtract_to_int32` is **kept** (unsigned encoder deltas).

**Bootloader CLI (firmware-update path):** greeting `bootloader=ready`; commands
`version info bank boot.mode flash erase crc copy rollback boot reset help`. Update flow:
app `update` → `bootloader=ready` → `info` (pick inactive bank) → `flash <bank>` (YMODEM:
STX 1024B blocks, CRC-16 poly 0x1021, EOT handshake) → `bank <bank>` → `boot`. All of this is
already implemented host-side in `../drdro-firmware-f4/tools/dro_update.py` — lift it.

**Board flash settings payload** (`shared/Settings.h`, the ONLY persisted fields):
`scale_num[4] scale_den[4] scale_sync[4] servo_max servo_acc servo_jog servo_mode`
(+ board-control fields the host doesn't own). Ping-pong A/B sectors, magic+CRC32, power-fail
safe, motion-safe `save`.

## Decisions — CONFIRMED (2026-06-29)

- **D2 — Fast poll:** **extend firmware `sta`** to also emit `servo.tgt` + `servo.mode`, so the
  30 Hz loop is a single round-trip. ⚑ **Cross-repo prerequisite** in `drdro-firmware-f4` (one
  extra `respKV` pair + native test) — must land before Phase 2's fast loop is final.
- **D3 — Bus serialization:** **`asyncio`, lock-guarded command queue** in `ProtocolClient`.
  Never blocks the Kivy loop (Kivy already runs under asyncio via `async_run`). `sta` benches
  >100 Hz → headroom to interleave `set`/`get`/`save` between polls.
- **D4 — Dynamic ratios stay in Python:** `scales.num/den` are unit-dependent, frequently
  changing ratio math → Python owns them, `set`s live on connect/change, **never `save`s** to
  flash. (So ratios *are* re-pushed on connect — intentional.)
- **D5/D6 — Persisted settings, firmware = source of truth:** `servo.max/acc/jog` live on the
  board. On connect **READ** them and sync Python (no push, replaces today's `on_connected`
  push); on UI change `set`+`save` (debounced). `scales.sync`/`servo.mode` are read-on-connect
  live state, set on change, not saved.

## Open / deferred decisions

- **D1** package name: `dro` applied in scaffold (vs keep `rcp` to zero-diff). Confirm if you'd
  rather keep `rcp`. *(default: `dro`)*
- **D7** firmware-update `.bin` source + whether to keep RCP's git/pip self-update screen:
  **deferred to Phase 5** — get the protocol working first. *(leaning: local file + GitHub; keep both)*

## Next steps (Phase 1)

1. (Optional) confirm D1; apply `rcp.` → `dro.` rename convention.
2. ⚑ Land the firmware `sta` extension in `drdro-firmware-f4` (Phase 0b) — coordinate before
   finalizing the Phase 2 fast loop.
3. Build `dro/comms/protocol_client.py`: **asyncio lock-guarded command queue**, framed
   request/response, crc verify, turnaround-glitch retry — port from `tools/dro_update.py`.
   (YMODEM `ymodem.py` + `updater.py` come in Phase 5.)
4. Re-point `dispatchers/board.py` + servo/axis/input to the protocol (mapping table §C.3).
5. Settings: **read** board on connect & sync Python (no push); `set`+`save` on UI change;
   ratios `set` live (never saved). Then the UI parity port.
6. See `docs/migration_todo.md` for the full Phase 0b–6 checklist.

## Commands

```bash
uv sync                       # install deps
uv run python -m dro.main     # run the app (once dro/main.py exists)
uv run pytest                 # tests
uv build                      # package
```

NixOS host: tools may not be on PATH — use `nix-shell -p <pkg> --run "<cmd>"` if needed.

## Conventions / gotchas

- **Logging:** `from kivy.logger import Logger; log = Logger.getChild(__name__)`. **Not** loguru.
- snake_case; keep firmware-mirror names where they aid cross-reference; dotted protocol names.
- Branches `main`/`dev`, conventional commits, `python-semantic-release`. **No AI attribution
  in commits/PRs.**
- Single half-duplex bus → only one command outstanding at a time; firmware-update mode takes
  exclusive port ownership (pause `sta`).
- RS-485 turnaround: first TX byte after a long RX can drop — read the full framed response and
  retry glitched commands (the updater already does this).
