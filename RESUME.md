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

- ✅ Repo initialized: uv project, branch `main`, `uv.lock` generated (`uv lock` green).
  Files: `pyproject.toml` (package `dro`, `pyserial` instead of `minimalmodbus`),
  `dro/__init__.py`, `.python-version` (3.11), `.gitignore`, `README.md`, `CLAUDE.md`.
- ✅ Design docs written and under review: `docs/migration_design.md` + `docs/migration_todo.md`.
- ⛔ **No code implemented yet.** Nothing committed — files are in the working tree awaiting
  the design review (decisions D1–D7).
- ⏳ **Next gate:** resolve open decisions D1–D7 (below) with the user, move them to
  "Confirmed" in the design doc, then start Phase 1.

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

## Two findings that shape the work

1. **`sta` poll gap (Decision D2):** the 30 Hz loop also needs `servo.tgt` (move done?) and
   `servo.mode` (enable state), which `sta` doesn't return. Options: (a) tiny firmware PR to
   add both to `sta` — recommended; (b) per-tick extra `get`s; (c) low-rate poll.
2. **Settings dynamic-ratio caveat (design §D.4):** `scales.num/den` is **not static** — RCP
   derives it from mechanical params **× MM/IN factor**, so it changes on unit/ratio edits.
   "Store on board" = board keeps last-applied values (no re-push on reconnect); host
   re-`set`+`save`s only on the deliberate user edit. Mechanical calibration, transforms,
   offsets, and UI prefs stay host-side. Full table in §D.3.

## Open decisions to resolve before Phase 1 (design doc §Open decisions)

- **D1** package name `dro` vs keep `rcp` *(proposed: `dro`)*
- **D2** fast-poll: extend firmware `sta` / extra gets / low-rate *(proposed: extend `sta`)*
- **D3** bus serialization: dedicated thread vs asyncio lock-queue *(proposed: thread+queue)*
- **D4** firmware `.bin` source: local file / GitHub releases / both *(proposed: both)*
- **D5** persist `scales.sync`/`servo.mode` or live-only *(proposed: live-only)*
- **D6** settings source-of-truth on mismatch *(proposed: board wins for persisted subset)*
- **D7** keep RCP's git/pip self-update screen alongside firmware updater *(proposed: keep both)*

## Next steps (Phase 1 starts here once decisions land)

1. Move D1–D7 to "Confirmed decisions" in `docs/migration_design.md`; apply package-name choice.
2. Build `dro/comms/protocol_client.py` (framed request/response, crc verify, turnaround-glitch
   retry — port from `tools/dro_update.py`). Add `dro/comms/ymodem.py` + `updater.py` (Phase 5).
3. Re-point `dispatchers/board.py` + servo/axis/input to the protocol (mapping table in §C.3).
4. Settings: read board on connect (no push); `save`-on-change. Then UI parity port.
5. See `docs/migration_todo.md` for the full Phase 1–6 checklist.

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
