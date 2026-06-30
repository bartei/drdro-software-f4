# drDRO Software — Migration & Port Todo

Phased one-liner tracker. Detail & rationale in `migration_design.md`. Tick `[x]` as items
land; keep the design doc as the source of truth. **D2/D3/D4/D5 confirmed; D1 defaulted to
`dro`; D7 (firmware-update source) deferred to Phase 5.**

## Phase 0 — Decisions & repo init
- [x] uv project scaffold (`pyproject.toml`, `.python-version`, `.gitignore`, `dro/` package)
- [x] Draft design doc + this tracker
- [x] Port `CLAUDE.md` coding standards from RCP (kivy.logger, naming, KV pattern)
- [x] Port `README.md` (host app overview + build/run)
- [x] `master` → `main`; first commit; `uv lock` green
- [x] Resolve key decisions: D2 (extend `sta`), D3 (asyncio queue), D4 (ratios in Python),
      D5/D6 (firmware = source of truth for persisted settings). D1=`dro`; D7 deferred.
- [ ] Confirm package name (D1) and apply `rcp.` → `dro.` rename convention

## Phase 0b — Cross-repo firmware prerequisite (drdro-firmware-f4)
- [ ] Extend firmware `sta` to also emit `servo.tgt` + `servo.mode` (one `respKV` pair + native
      test) — needed before Phase 2 fast loop is finalized. **Tracked in the firmware repo.**

## Phase 1 — Protocol client (driver replacement core)
- [ ] `dro/comms/protocol_client.py`: `serial.Serial` owner, framed request/response
- [ ] Response reader: read until blank line, parse `key=value`, verify `crc=HH`
- [ ] RS-485 turnaround-glitch tolerance + retry (port from `dro_update.py`)
- [ ] `get` / `set` (with array `idx`) / `settings` / `sta` / `version` / `help`
- [ ] `save` / `load` (board flash)
- [ ] Optional `*HH` request checksum (off by default)
- [ ] `MAX_ERROR_COUNT` resilience / connected-state semantics
- [ ] Bus serialization (D3): asyncio lock-guarded command queue; never block the Kivy loop
- [ ] Unit tests against captured wire frames (mock serial) — mirror firmware `test_protocol`
- [ ] Keep `dro/utils/ctype_calc.py`; delete the Modbus parser path

## Phase 2 — Dispatchers re-pointed to the protocol (needs Phase 0b firmware `sta`)
- [ ] `board.py`: `ProtocolClient` instead of `ConnectionManager`; `update` loop polls `sta`
- [ ] Fast-poll: single-round-trip `sta` → `scales.pos/speed`, `servo.pos/speed`, `servo.tgt`, `servo.mode`
- [ ] `servo.py`: `maxSpeed/acc/jog`→`servo.max/acc/jog`; `direction`→`servo.tgt`; `servoEnable`→`servo.mode`
- [ ] `axis.py`: `_set_sync_ratio` → `set scales.num/den`; `toggle_sync` → `set scales.sync`
- [ ] `input.py`: scale position/speed from `sta` mapping
- [ ] `statusbar`: `diag.cycles` / `diag.interval` via low-rate `get`
- [ ] Verify identical UI behaviour vs RCP on the bench

## Phase 3 — Settings: firmware = source of truth (stop push-on-reconnect)
- [ ] On connect: **read** persisted settings (`servo.max/acc/jog`) from board → sync Python (no push)
- [ ] Remove `on_connected` push of `maxSpeed`/`acceleration`; replace with read-back
- [ ] On UI change of `servo.max/acc/jog`: `set` + `save` (debounced)
- [ ] `scales.num/den`: derive in Python, `set` on connect/change, **never `save`** (D4)
- [ ] `scales.sync` / `servo.mode`: read-on-connect to sync UI; `set` on change; not saved (D5)
- [ ] Drop Modbus `address` from `config.ini`

## Phase 4 — UI feature parity port (1:1)
- [ ] Screens (18) + `.kv` — see design §F
- [ ] Home modes + bars (Index/ELS/Jog/DRO, coordbar/servobar/elsbar/jogbar/statusbar)
- [ ] Popups (keypad/help/mode/feeds/ssid)
- [ ] Widgets (number/dual_number/boolean/dropdown/string/color/font/button/title/…)
- [ ] Plot (scene/float_view/coords_overlay/toolbar + circle/line/rect popups)
- [ ] Pattern dispatchers + `axis_transform` + `formats` + `els` + `saving_dispatcher`
- [ ] Platform utils (`platform.py`, `kv_loader.py`), `feeds.py`, help `.rst`, fonts
- [ ] `app.py` / `main.py` / `manager.py` / `appsettings.py`
- [ ] Keep RCP git/pip self-update screen (D7)
- [ ] Parity pass: every RCP screen/feature exercised on hardware

## Phase 5 — Firmware update & bank management (new feature)
- [ ] `dro/comms/ymodem.py` (YMODEM sender; port from `dro_update.py`)
- [ ] `dro/comms/updater.py` (orchestrate update→info→flash→bank→boot, progress callbacks)
- [ ] Bootloader CLI client coverage (`info bank boot.mode flash erase crc copy rollback boot reset`)
- [ ] Firmware screen: pick `.bin` (local; GitHub later per D4), progress, bank status, rollback
- [ ] Exclusive bus ownership during update (pause `sta`)
- [ ] Bench: end-to-end firmware update + rollback from the UI

## Phase 6 — Release & polish
- [ ] CI (GitHub Actions) build + tests; `python-semantic-release` on main/dev
- [ ] Sentry init parity; logging parity (kivy.logger)
- [ ] Final cleanup of RCP dead code not carried over (beep, TraceOutput — see RCP todo)
- [ ] User-facing notes for the Modbus→protocol switch
