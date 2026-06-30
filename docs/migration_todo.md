# drDRO Software — Migration & Port Todo

Phased one-liner tracker. Detail & rationale in `migration_design.md`. Tick `[x]` as items
land; keep the design doc as the source of truth. **Nothing started — review the design and
resolve the open decisions (D1–D7) first.**

## Phase 0 — Decisions & repo init
- [x] uv project scaffold (`pyproject.toml`, `.python-version`, `.gitignore`, `dro/` package)
- [x] Draft design doc + this tracker
- [ ] Resolve open decisions D1–D7 (design doc §Open decisions)
- [ ] Port `CLAUDE.md` coding standards from RCP (kivy.logger, naming, KV pattern)
- [ ] Port `README.md` (host app overview + build/run)
- [ ] `master` → `main`; first commit; `uv sync` green
- [ ] Confirm package name (D1) and apply `rcp.` → `dro.` rename convention

## Phase 1 — Protocol client (driver replacement core)
- [ ] `dro/comms/protocol_client.py`: `serial.Serial` owner, framed request/response
- [ ] Response reader: read until blank line, parse `key=value`, verify `crc=HH`
- [ ] RS-485 turnaround-glitch tolerance + retry (port from `dro_update.py`)
- [ ] `get` / `set` (with array `idx`) / `settings` / `sta` / `version` / `help`
- [ ] `save` / `load` (board flash)
- [ ] Optional `*HH` request checksum (off by default)
- [ ] `MAX_ERROR_COUNT` resilience / connected-state semantics
- [ ] Bus serialization (D3): single outstanding command at a time
- [ ] Unit tests against captured wire frames (mock serial) — mirror firmware `test_protocol`
- [ ] Keep `dro/utils/ctype_calc.py`; delete the Modbus parser path

## Phase 2 — Dispatchers re-pointed to the protocol
- [ ] `board.py`: `ProtocolClient` instead of `ConnectionManager`; `update` loop polls `sta`
- [ ] Fast-poll mapping per D2 (`sta` → `scales.pos/speed`, `servo.pos/speed` + tgt/mode)
- [ ] `servo.py`: `maxSpeed/acc/jog`→`servo.max/acc/jog`; `direction`→`servo.tgt`; `servoEnable`→`servo.mode`
- [ ] `axis.py`: `_set_sync_ratio` → `set scales.num/den`; `toggle_sync` → `set scales.sync`
- [ ] `input.py`: scale position/speed from `sta` mapping
- [ ] `statusbar`: `diag.cycles` / `diag.interval` via low-rate `get`
- [ ] Verify identical UI behaviour vs RCP on the bench

## Phase 3 — Settings: board flash vs host (stop push-on-reconnect)
- [ ] On connect: read board settings (`settings`/`get`) into dispatchers (no push)
- [ ] Remove `on_connected` push of `maxSpeed`/`acceleration`; replace with read-back
- [ ] `save`-on-change (debounced) for the persisted subset (D.3 table)
- [ ] Re-`set`+`save` `scales.num/den` on unit (MM/IN) or sync-ratio change (D.4 caveat)
- [ ] Source-of-truth reconciliation on mismatch (D6)
- [ ] Decide & wire `scales.sync` / `servo.mode` persistence (D5)
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
