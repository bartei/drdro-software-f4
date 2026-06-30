# drDRO Software — Migration & Port Design

> **Status: DRAFT for review (2026-06-29).** Verbose design lives here; phased work
> with one-liner checkboxes lives in `migration_todo.md`. Nothing is implemented yet —
> we review this document together, tick the open decisions, and only then start the
> port. Mirrors the firmware repo's `docs/` convention (design doc + todo tracker).

Goal of this project (`drdro-software-f4`): **port 1:1** every feature of the existing
Kivy host app `rotary-controller-python` (hereafter **RCP**), then **replace its driver
layer** — currently RS-485 **Modbus RTU** via `minimalmodbus` — with the new firmware's
**custom CLI line protocol** over RS-485. Once parity is reached, add **firmware-update
and bank management** over the same bus, and **move static configuration into the board's
flash settings** instead of re-pushing it to the board on every reconnect.

The new firmware (`drdro-firmware-f4`) is **already shipped and HW-verified** (protocol +
dual-bank IAP bootloader + persistent settings, ≥ v0.2.2). This project is the host side
that talks to it. Authoritative firmware references (read these alongside this doc):
`drdro-firmware-f4/docs/protocol_design.md`, `dualbank_design.md`, `shared/Settings.h`,
`shared/Bootloader.h`, and the working host updater `drdro-firmware-f4/tools/dro_update.py`.

---

## Part A — Repository & project setup

- **Tooling:** `uv`-managed Python project (`pyproject.toml`, `uv.lock` committed).
  `uv sync` / `uv run python -m dro.main` / `uv run pytest` / `uv build`.
- **Python:** 3.10+ (matches RCP). `.python-version` pins 3.11 for the dev venv.
- **Package name:** `dro` (was `rcp`). See **Decision D1** — a flat package mirroring
  RCP's `rcp/` layout, minimizing port churn. KV files reference the runtime `app`
  object, not import paths, so the rename is mostly a mechanical `from rcp.` → `from dro.`
  find/replace in `.py` files.
- **Dependencies (initial `pyproject.toml`):** `kivy`, `pyserial` (NEW — replaces
  `minimalmodbus`), `pydantic`, `pyyaml`, `nmcli`, `aiohttp`, `sentry-sdk`, `keke`,
  `cachetools`. Dev: `pytest`, `coverage`, `python-semantic-release`.
- **Removed dep:** `minimalmodbus` (Modbus gone). **Added dep:** `pyserial` (raw serial
  for the line protocol + YMODEM firmware push).
- **Branches / releases:** `main` (releases) / `dev` (pre-releases), conventional commits,
  `python-semantic-release` — same as RCP and the firmware repo. Initial branch renamed
  `master` → `main`. No AI/Claude attribution in commits (firmware-repo convention).
- **Coding standards:** carry over RCP's `CLAUDE.md` verbatim (snake_case; firmware-mirror
  names kept as-is; **`kivy.logger`, not loguru**; KV-loading pattern; `SavingDispatcher`
  YAML persistence). A ported `CLAUDE.md` ships in this repo.

---

## Part B — What we are porting (source architecture recap)

RCP is layered. Only the **bottom layer is replaced**; everything above is ported as-is.

| Layer | RCP modules | Disposition |
|---|---|---|
| **Driver / comms** | `utils/communication.py` (Modbus `ConnectionManager` + register R/W), `utils/base_device.py` (C-typedef parser + bulk `refresh`), `utils/devices.py` (struct typedefs), `utils/ctype_calc.py` | **REPLACED** by the line-protocol client (Part C). `ctype_calc` is **kept** (encoder wrap math). |
| **Dispatchers / state** | `dispatchers/board.py`, `axis.py`, `input.py`, `servo.py`, `els.py`, `formats.py`, `axis_transform.py`, `circle_pattern.py`, `line_pattern.py`, `rect_pattern.py`, `saving_dispatcher.py` | **Ported.** Only the calls that read/write the device change (Part C.3). |
| **UI components** | `components/screens/*` (18), `components/home/*` (mode layouts + bars), `components/popups/*`, `components/widgets/*`, `components/plot/*`, `components/toolbars/*`, `manager.py`, `appsettings.py` | **Ported 1:1**, including `.kv` files. |
| **Platform utils** | `utils/platform.py` (Pi detect, partition resize), `utils/kv_loader.py` | **Ported as-is** (host-only; no device coupling). |
| **App / entry** | `app.py` (`MainApp`), `main.py` (asyncio + Kivy loop), `feeds.py` (thread/feed tables) | **Ported.** |

The full screen/component inventory is in **Part F** (the parity checklist source).

---

## Part C — Driver layer replacement (the core change)

### C.1 The old model (Modbus, being removed)

- `ConnectionManager` wraps a `minimalmodbus.Instrument` (slave address **17**, 115200).
- `devices.py` declares the board's shared struct as **C-typedef strings**; `base_device.py`
  parses them into a register map (`name → address, type, count`) and supports:
  - **bulk read:** `device['fastData'].refresh()` does chunked `read_registers` over the
    whole struct each 30 Hz tick → a `fast_data_values` dict (Modbus registers are 16-bit;
    32-bit/float values span two registers, little-swap byte order).
  - **scalar R/W by address:** `device['servo']['maxSpeed'] = v` → `write_float(addr, v)`.
- **Resilience:** `MAX_ERROR_COUNT = 5` consecutive errors before declaring the link down;
  transient glitches don't trigger a reconnect.

### C.2 The new model (custom line protocol)

Replace register-by-address access with **named-variable access** over a text line protocol.
Single device on the bus → **no addressing**. RS-485 auto-direction transceiver → host does
nothing for direction; it's a plain half-duplex serial port at **115200** (fixed).

**Wire format (authoritative — confirmed from firmware source & tests):**
- **Request:** `command [args] [*HH]\n`. `*HH` = optional uppercase-hex **XOR-8** of the bytes
  before `*`; firmware validates if present, accepts if absent (CLI-friendly). Terminators
  `\r`, `\n`, or `\r\n` all accepted. A lone `\n` **repeats the last command** (1-byte re-poll).
- **Response:** zero or more `key=value\n` body lines, then a **`crc=HH\n`** line (XOR-8 over
  the body), then a **terminating blank line** (`\n`). Client reads lines until the blank line.
  Presence of an `error=<reason>` line ⇒ failure.
- **Arrays:** one grouped line, comma-joined: `scales.pos=12345,988,0,42`.

**New module `dro/comms/protocol_client.py`** (replaces `communication.py` + `base_device.py`):
a `ProtocolClient` owning the `serial.Serial` port with:
- `command(cmd, *, timeout, retries)` → parsed `dict` (frames a request, reads until blank
  line, verifies `crc`, retries on the RS-485 turnaround glitch — port the robust read/retry
  logic straight from `tools/dro_update.py:read_response`/`cli`).
- `get(name)` / `set(name, value, idx=None)` / `settings()` / `sta()` / `version()`.
- `save()` / `load()` (board flash persistence — Part D).
- Bootloader/firmware-update methods (Part E).
- The same `MAX_ERROR_COUNT` resilience semantics as the old `ConnectionManager`.

### C.3 Variable registry & the access-mapping table

The C-typedef parser is **gone**; the variable set is now a small static table the firmware
defines. These are the **real, implemented** names (verified in firmware `Protocol.c`, not the
design proposal):

| Protocol var | Type | Count | RW | Firmware field | Replaces RCP access |
|---|---|---|---|---|---|
| `scales.pos`   | i32 | 4 | RW | `scales[i].position`     | `fast_data_values['scaleCurrent'][i]`; set current pos |
| `scales.speed` | i32 | 4 | RO | `scales[i].speed`        | `fast_data_values['scaleSpeed'][i]` |
| `scales.num`   | i32 | 4 | RW | `scales[i].syncRatioNum` | `device['scales'][i]['syncRatioNum']` |
| `scales.den`   | i32 | 4 | RW | `scales[i].syncRatioDen` | `device['scales'][i]['syncRatioDen']` |
| `scales.sync`  | u16 | 4 | RW | `scales[i].syncEnable`   | `device['scales'][i]['syncEnable']` |
| `servo.max`    | f32 | 1 | RW | `servo.maxSpeed`         | `device['servo']['maxSpeed']` |
| `servo.acc`    | f32 | 1 | RW | `servo.acceleration`     | `device['servo']['acceleration']` |
| `servo.jog`    | f32 | 1 | RW | `servo.jogSpeed`         | `device['servo']['jogSpeed']` |
| `servo.mode`   | u16 | 1 | RW | `fastData.servoMode`     | `device['fastData']['servoEnable']` (0=off,1=sync/index,2=jog) |
| `servo.pos`    | u32 | 1 | RO | `servo.currentSteps`     | `fast_data_values['servoCurrent']` |
| `servo.speed`  | f32 | 1 | RO | `servo.currentSpeed`     | `fast_data_values['servoSpeed']` |
| `servo.tgt`    | i32 | 1 | RW | `servo.stepsToGo`        | `fast_data_values['stepsToGo']` (read) / `device['servo']['direction']=Δ` (write = start move) |
| `diag.cycles`  | u32 | 1 | RO | `fastData.cycles`        | `fast_data_values['cycles']` |
| `diag.interval`| u32 | 1 | RO | `fastData.executionInterval` | `fast_data_values['executionInterval']` |

**Naming note:** RCP's `servoEnable` (already used with 0/1/2 semantics — jogbar sets 2)
maps cleanly to the firmware's `servo.mode`. RCP's servo `direction` (the start-an-indexed-move
write) maps to `servo.tgt` (firmware renamed `direction` → `stepsToGo`).

**App CLI commands:** `sta set get settings save load bank rollback version help update reset`.
**Errors:** `unknown command`, `unknown variable`, `usage: …`, `read-only`, `bad index`,
`value out of range`, `bad checksum`, `flash write`.

### C.4 Fast-poll mapping — `sta` vs the old bulk `refresh` ✅ CONFIRMED (D2)

The 30 Hz UI loop (`board.update`) currently calls `device['fastData'].refresh()` and every
dispatcher reads from the resulting `fast_data_values` dict. The new firmware's `sta` returns
**only**: `scales.pos`, `scales.speed`, `servo.pos`, `servo.speed`.

The host's per-tick consumers need **two more** values:
- `stepsToGo` → `servo.tgt` — used by `ServoDispatcher.on_update_tick` to detect move
  completion (`stepsToGo == 0` re-enables controls / restores max speed).
- `servoEnable` → `servo.mode` — used each tick to track enable state.

**Decision (confirmed):** **extend the firmware `sta` response** to also emit `servo.tgt` and
`servo.mode`, so the fast loop stays a **single round-trip**. This is a small, coordinated
firmware change in `drdro-firmware-f4` (one extra `respKV` pair in the `sta` handler + its
native test). ⚑ **Cross-repo action item** — must land in firmware before Phase 2's fast
loop is finalized; track it there. `sta` already benchmarks well over 100 Hz, so the extra
two fields cost nothing meaningful against the 30 Hz UI rate.

After the firmware change, the per-tick `sta` yields everything the hot loop needs:
`scales.pos[4]`, `scales.speed[4]`, `servo.pos`, `servo.speed`, `servo.tgt`, `servo.mode`.

`diag.cycles`/`diag.interval` (statusbar FPS/interval readout) stay **out** of the hot loop —
fetch via a periodic low-rate `get`.

### C.5 Connection lifecycle & resilience

- Open `serial.Serial(port, 115200, timeout=…)`; no slave address, no Modbus framing.
- Reuse RCP's `MAX_ERROR_COUNT` debounce so a transient glitch doesn't bounce the link.
- **RS-485 turnaround glitch:** the firmware's first TX byte after a long RX can be dropped
  (`dro_update.py` documents this). Port its tolerant reader: read the full framed response,
  verify `crc`, and retry a command whose reply is empty/`unknown command` (these are all
  valid commands, so that's a glitch, not a real error).
- **CRC verification:** check the response `crc=HH` line; a mismatch counts as an error
  (feeds the debounce). Optionally send the `*HH` request checksum once link quality is
  characterised (off by default — CLI-friendly).

### C.6 Bus access serialization ✅ CONFIRMED (D3)

Modbus `minimalmodbus` is request/response and the old code was effectively single-threaded
from the Kivy clock. The line protocol is also strictly request/response on a single
half-duplex bus, so **only one command may be outstanding at a time**.

**Decision (confirmed):** an **`asyncio`, lock-guarded command queue** inside `ProtocolClient`.
Callers (the Kivy loop, UI actions, the updater) **enqueue** a command and `await`/get-back its
parsed response; the queue serializes the wire so nothing interleaves or mixes up, and the Kivy
event loop is never blocked on serial I/O. `main.py` already runs Kivy under `asyncio`
(`async_run`), so the queue lives on the same loop. The 30 Hz `update_tick` enqueues `sta` and
applies the result when it returns; occasional `set`/`get`/`save` slot in between polls. The
protocol was benchmarked **well over 100 Hz** for `sta`, so there is ample headroom to
interleave other requests against the 30 Hz UI rate.

Firmware-update mode takes **exclusive** ownership of the port: the `sta` poll is paused for the
duration of the YMODEM transfer (the updater drains/holds the queue), then resumed.

---

## Part D — Settings storage assessment (board flash vs host) ⚠️ central goal

### D.1 Current behaviour (push-on-reconnect)

Today the host treats the board as **stateless** and re-pushes config every time the link
comes up:
- `ServoDispatcher.on_connected` writes `servo.maxSpeed` + `servo.acceleration` on every
  `connected` transition.
- `AxisDispatcher._init_connection` reads back `syncEnable` and re-derives + writes
  `scales[i].syncRatioNum/Den` via `_set_sync_ratio`.
- `toggle_sync` writes `scales[i].syncEnable` on demand.

The new firmware has **persistent flash settings** (`shared/Settings.h`, ping-pong A/B
sectors, magic+CRC32, power-fail safe). The goal: **stop re-pushing on reconnect**; write
config once with `save`, and on connect **read it back** (`settings`/`get`) to sync the UI.

### D.2 What the firmware flash can hold

`settings_t` payload (the **only** fields the board persists) — must not be reordered without
bumping `SETTINGS_VERSION`; both app & bootloader **read-modify-write the whole struct**:

```
scale_num[4]  scale_den[4]  scale_sync[4]   servo_max  servo_acc  servo_jog  servo_mode
```
(plus board-control fields the host doesn't own: `boot_mode`, `active_bank`, `loaded_bank`,
`bank_crc[2]`, `seq`, `magic`, `version`, `crc`).

### D.3 Classification — store-on-board vs keep-in-host

**Rule (from the brief):** values that **rarely change** (only on hardware/mechanical change)
→ board flash; values that **change often** → host (YAML/`config.ini`).

| Setting | Where | Change frequency | Rationale |
|---|---|---|---|
| `scales.num[4]` / `scales.den[4]` (final sync ratios) | **Host (Python) — set live, NOT saved** ✅D4 | frequent | Complex ratio math that changes often and **depends on the MM/IN display unit**. Python is the source of truth; it derives them and **pushes (`set`) on connect and on change**, but **never `save`s** them to flash. **See D.4.** |
| `servo.max`, `servo.acc`, `servo.jog` | **Board flash (firmware = source of truth)** ✅D5 | rare | Config values `on_connected` re-pushes today. Persist on the board; **read on connect**, `set`+`save` on UI change. |
| `scales.sync[4]` (enable) | **Live operational — read on connect, not saved** ✅D5 | medium | Toggle (`toggle_sync`); `set` live, **read** on connect to sync the UI to actual board state. Not persisted. |
| `servo.mode` | **Live operational — read on connect, not saved** ✅D5 | medium | Off/sync/jog; `set` live, **read** on connect to sync the UI. Not persisted. |
| Input mechanical calibration: `ratioNum/ratioDen`, `stepsPerMM`, `encoder_ppr`, `gear_ratio_num/den`, `spindleMode` (`InputDispatcher`) | **Host YAML** | rare but **host-only concept** | Firmware has no notion of these; they feed host display math and the sync-ratio derivation. Stay in `CoordBar-*.yaml`. |
| Servo mechanical: `ratioNum/ratioDen` (steps/turn), `unitsPerTurn`, `leadScrewPitch/In/Steps`, `elsMode`, `divisions`, `indexSpeed` | **Host YAML** | rare but **host-only** | Used to derive `scales.num/den` and for display; firmware only sees the final ratio. |
| Axis: `transform`, `axis_name`, `axis_index`, user `syncRatioNum/Den`, `offsets[100]`, `abs_offset` | **Host YAML** | often (offsets) / rare (transform) | Host abstraction; no firmware equivalent. |
| Tool/offset state: `currentOffset`, `tool`, `abs_inc` | **Host config** | often | Per-operation. |
| Display/UI: formats (MM/IN `factor`), colors, fonts, speed units, `display_color`, `hide_mouse_cursor` | **Host config/YAML** | often / preference | Pure UI. |
| ELS role assignments (`spindle/z/x_axis_index`) | **Host YAML** | rare, host-only | Host mapping. |
| Connection: `serial_port`, `baudrate` | **Host `config.ini`** | rare | Host-side. **`address` (Modbus slave 17) is removed** — no addressing. |

### D.4 The dynamic ratios stay in Python ✅ CONFIRMED (D4)

`scales.num/den` is **not a constant** in RCP: `AxisDispatcher._set_sync_ratio` derives it as
`scale_ratio × user_sync ÷ servo_ratio`, and `scale_ratio` **includes the MM/IN `factor`**, so
the value changes whenever the user flips units or edits a ratio.

**Decision (confirmed):** these dynamic ratios are **not stored on the board**. Python owns the
calculation and **pushes them with `set`** — on connect and whenever a contributing value
(unit, user sync ratio, mechanical params) changes — but **never `save`s** them to flash. The
board's flash `scale_num/den` fields simply retain their defaults; Python overwrites the live
values each connect. This keeps the complex, unit-dependent math entirely on the host where it
belongs. (Consequence: ratios *are* re-pushed on connect — that's intentional and cheap; only
the **persisted** subset below stops being pushed.)

### D.5 Connect flow & `save` policy — firmware is source of truth ✅ CONFIRMED (D5/D6)

For the **board-persisted** settings (`servo.max`, `servo.acc`, `servo.jog`), the **firmware is
the source of truth**:

- **On connect: READ, don't push.** Fetch the board's persisted values (`settings` or targeted
  `get`s) and **sync the Python side to them** — replacing today's `on_connected` push of
  `maxSpeed`/`acceleration`. The board's stored config wins.
- **On UI change: `set` + `save`.** When the user edits one of these in the UI, push it
  (`set`) and persist it (`save`, debounced). Never `save` per tick. `save` is motion-safe
  (firmware ISR runs from RAM), so it's safe at any time.
- **Live operational state** (`scales.sync`, `servo.mode`): **read on connect** to sync the UI
  to the board's actual state, `set` on change, **not** `save`d.
- **Dynamic ratios** (`scales.num/den`): `set` on connect/change, **not** `save`d (§D.4).
- **Whole-struct RMW:** the firmware preserves untouched fields, but when saving the host should
  ensure the intended fields are current so a stale in-RAM image isn't written back.

---

## Part E — Firmware update & bank management (new feature)

This realises the long-standing RCP todo *"STM32 firmware flashing from Pi"* and is **distinct**
from RCP's existing `update_screen.py`, which git-pulls + pip-installs the **host app** itself.
Both can coexist: one updates the Python software, the new one flashes the **board firmware**
over RS-485.

**Mechanism (port `drdro-firmware-f4/tools/dro_update.py` into the app):**
1. App command `update` → board jumps to the bootloader; wait for greeting `bootloader=ready`.
2. Bootloader CLI `info` → read `bank.active` / `bank.loaded` / `bank{0,1}.valid` / `exec.valid`;
   pick the inactive bank.
3. `flash <bank>` → **YMODEM send** the firmware `.bin` (self-contained sender: STX 1024-byte
   blocks, CRC-16 poly 0x1021, EOT handshake — already implemented in `dro_update.py`).
4. `bank <bank>` → select active bank (persisted to flash).
5. `boot` → bootloader copies active bank → Exec and jumps to the new app.

**Bootloader CLI command set (real):** `version info bank boot.mode flash erase crc copy
rollback boot reset help`; greeting `bootloader=ready`.

**Host pieces to build:**
- `dro/comms/ymodem.py` — YMODEM sender (lift from `dro_update.py`).
- `dro/comms/updater.py` — the orchestration above, with progress callbacks.
- A **firmware screen** (new): pick a `.bin` (local file and/or download from the firmware
  repo's GitHub releases — **Decision D4**), show transfer progress, display bank status
  (active/loaded/valid), and offer **rollback**. The `ProtocolClient` must take exclusive bus
  ownership (stop `sta` polling) for the duration.
- Reuse the framed-CLI reader (Part C.5) — the bootloader speaks the **byte-identical** wire
  format, so one client drives both app and bootloader.

---

## Part F — Feature parity inventory (1:1 port checklist source)

Everything below is ported. Device-touching items route through the new `ProtocolClient`;
everything else is a straight port (including `.kv` files).

- **Screens (18):** `home`, `setup`, `axes_setup`, `axis`, `els_setup`, `servo`, `formats`,
  `network` (nmcli WiFi), `update` (git/pip self-update — keep as-is), `system` (Pi partition
  resize + reboot), `color_picker`, `font_picker`, `input`, `inputs_setup`, `logs`,
  `log_viewer`, `profiling`. **NEW:** firmware screen (Part E).
- **Home / modes:** `home_toolbar`, `statusbar` (now reads `diag.*`), `coordbar`,
  `dro_coordbar`, `servobar`, `elsbar`, `jogbar`, and the four `*_mode_layout`s
  (Index / ELS / Jog / DRO) + `mode_layout` base.
- **Popups:** `keypad` (numeric entry + min/max validation), `help_popup` (RST), `mode_popup`,
  `feeds_table_popup`, `ssid_popup`.
- **Widgets:** `number_item`, `dual_number_item`, `boolean_item`, `dropdown_item`,
  `string_item`, `color_item`, `font_item`, `button_item`, `title_item`, `auto_size_button`,
  `keypad_button`, `keypad_icon_button`, `screen_header`.
- **Plot:** `plot_screen`, `scene`, `float_view` (pan + pinch-zoom), `coords_overlay`,
  `plot_toolbar`, `circle_popup`, `line_popup`, `rect_popup`.
- **Dispatchers:** `board`, `axis`, `input`, `servo`, `els`, `formats`, `axis_transform`,
  `circle_pattern`, `line_pattern`, `rect_pattern`, `saving_dispatcher`.
- **Utils:** `platform` (Pi detect, `growpart`/`resize2fs`, `lsblk`/`df`/`findmnt`),
  `kv_loader`, `ctype_calc` (kept). **Removed:** `communication`, `base_device`, `devices`.
- **App/entry/data:** `app.py`, `main.py`, `feeds.py`, `appsettings.py`, `manager.py`,
  help `.rst` files, fonts.

---

## Part G — Removed / changed vs RCP

- **Removed:** `minimalmodbus` dep; Modbus slave address (17); the C-typedef register parser
  (`base_device.py`, `devices.py`); per-address read/write helpers in `communication.py`.
- **Added:** `pyserial`; `ProtocolClient`; YMODEM sender + firmware updater; board-flash
  settings sync; firmware-management UI.
- **Changed behaviour:** no push-on-reconnect (read-back instead); `save`-on-change to flash;
  `servoEnable` semantics now explicitly `servo.mode`; `sta` fast-poll shape (Part C.4).
- **Kept:** `ctype_calc.uint32_subtract_to_int32` (encoder wraparound delta — still needed for
  `scales.pos`/`servo.pos` unsigned deltas).

---

## Open decisions

- **D1 — Package name:** `dro` applied in the scaffold (vs keeping `rcp`). Not explicitly
  confirmed; speak up if you'd rather zero-diff the port by keeping `rcp`. *(default: `dro`)*
- **D7 — Firmware `.bin` source for the updater** (local file picker vs GitHub-releases
  download vs both): **deferred** — get the protocol rolled out and working first, then
  decide when we build the firmware screen (Phase 5). *(leaning: both, local file first)*

> Note: the earlier "D4 — firmware `.bin` source" question was renumbered to **D7** so D4 now
> refers to the dynamic-ratio decision (§D.4). The "keep RCP's git/pip self-update screen"
> question is also deferred to Phase 5.

## Confirmed decisions
- **D2 — Fast poll:** **extend firmware `sta`** to also emit `servo.tgt` + `servo.mode` →
  single-round-trip hot loop. Cross-repo firmware change (§C.4).
- **D3 — Bus serialization:** **`asyncio`, lock-guarded command queue** in `ProtocolClient`;
  never blocks the Kivy loop; `sta` >100 Hz gives headroom to interleave (§C.6).
- **D4 — Dynamic ratios:** `scales.num/den` stay **in Python** (unit-dependent, frequently
  changing); `set` live, **never `save`d** to flash (§D.4).
- **D5/D6 — Persisted settings:** **firmware is the source of truth** for `servo.max/acc/jog`.
  On connect **read** board values and sync Python (no push); on UI change `set`+`save`.
  `scales.sync`/`servo.mode` are read-on-connect live state, not persisted (§D.5).

## Parking lot (future, not now)
- Multi-board addressing (firmware parking-lot too).
- Request checksums (`*HH`) on by default once link quality is characterised.
- Bundling a known-good firmware `.bin` with the host release for offline flashing.
