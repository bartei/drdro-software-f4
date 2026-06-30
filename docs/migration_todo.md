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

## Phase 1 — Protocol client (driver replacement core) — done 2026-06-29, HW-verified
- [x] `dro/comms/protocol_client.py`: `serial.Serial` owner, framed request/response
- [x] Response reader: read until blank line, parse `key=value`, verify `crc=HH` (`parse_response`)
- [x] RS-485 turnaround-glitch tolerance + retry (glitch heuristic on unknown command/variable + crc fail)
- [x] `get` / `set` (with array `idx`) / `settings` / `sta` / `version` (`help` via `command()`)
- [x] `save` / `load` (board flash)
- [x] Optional `*HH` request checksum (`request_checksum` flag; HW-validated end-to-end)
- [x] `MAX_ERROR_COUNT` resilience / connected-state semantics
- [x] Bus serialization (D3): asyncio lock-guarded queue + single-thread executor; never blocks Kivy
- [x] Unit tests (15) against a firmware-accurate `FakeSerial` — crc/retry/error/link-state
- [x] **HW-verified** against the board over `/dev/ttyACM2`: version/sta/get/set/settings/RO-error,
      checksummed requests, read+write round-trips, restore. All CRC-correct, link stayed up.
- [x] Keep `dro/utils/ctype_calc.py` (encoder-wrap helper ported in Phase 2)

## Phase 2 — Dispatchers re-pointed to the protocol — done 2026-06-29, HW-verified
- [x] `board.py`: owns `ProtocolClient`; async poll loop (`run`/`poll_once`) replaces the
      Clock-driven Modbus refresh; sync↔async bridge (`write`/`write_persisted`/`cached`/`_spawn`)
- [x] Fast-poll: single-round-trip `sta` → `map_sta` (scales.pos/speed, servo.pos/speed/tgt/mode)
- [x] `servo.py`: `maxSpeed/acc/jog`→`servo.max/acc/jog`; `direction`→`servo.tgt`; `servoEnable`→`servo.mode`;
      board-as-source-of-truth sync on connect (`_sync_from_board`, write-back suppressed)
- [x] `axis.py`: `_set_sync_ratio` → live `set scales.num/den` (never saved, D4); `toggle_sync` → `set scales.sync`
- [x] `input.py`: scale position/speed from the `sta` mapping
- [x] `els.py` ported; `ctype_calc`, `saving_dispatcher`, `formats`, `axis_transform` ported
- [x] Board folds `diag.cycles`/`diag.interval` into `fast_data_values` via a low-rate `get`
      (statusbar *widget* itself is Phase 4 UI)
- [x] Settings flow wired (Phase 3 overlaps): read board on connect (no push), `set`+debounced
      `save` on persisted UI change, ratios live-only
- [x] Unit tests (map_sta + cache, 4) + **HW harness**: Board+dispatchers drive the live board —
      connected, fast_data_values populated, servo synced from flash, persisted + live writes round-trip
- [ ] Verify identical UI behaviour vs RCP on the bench — deferred to Phase 4 (UI not built yet)

## Phase 3 — Settings: firmware = source of truth (landed with Phase 2)
- [x] On connect: **read** persisted settings (`servo.max/acc/jog`) → sync Python (no push)
      (`Board._refresh_settings` + `ServoDispatcher._sync_from_board`)
- [x] Removed `on_connected` push of `maxSpeed`/`acceleration`; replaced with read-back
- [x] On UI change of `servo.max/acc/jog`: `set` + debounced `save` (`Board.write_persisted`)
- [x] `scales.num/den`: derived in Python, `set` on connect/change, **never `save`** (D4)
- [x] `scales.sync` / `servo.mode`: read-on-connect to sync UI; `set` on change; not saved (D5)
- [x] Dropped Modbus `address` from `config.ini` (client has no addressing)

## Phase 4 — UI feature parity port (1:1) — built & rendering 2026-06-29
- [x] Screens (19) + `.kv` ported; Manager instantiates them all at startup
- [x] Home modes + bars (Index/ELS/Jog/DRO, coordbar/servobar/elsbar/jogbar/statusbar)
- [x] Popups (keypad/help/mode/feeds/ssid), Widgets (number/dual/boolean/dropdown/…), Plot (+circle/line/rect)
- [x] Pattern dispatchers (circle/line/rect) + `axis_transform` + `formats` + `els` + `saving_dispatcher`
- [x] Platform utils (`platform.py`, `kv_loader.py`), `feeds.py`, help `.rst`, fonts/pictures/sounds
- [x] `app.py` (resource paths, serial cfg → Board, `board.start()`) / `main.py` / `manager.py` / `appsettings.py`
- [x] Kept RCP git/pip self-update screen (D7 — both updaters coexist)
- [x] `rcp.`→`dro.` rewrite incl. bare KV `#: import` targets; `~/.config/drdro-software` config dir
- [x] **App builds & renders headless (Xvfb+SDL2/GL)**: all 19 screens instantiate, 51 KV files load,
      home screen renders live against the board (screenshot). Package version v0.1.0 shown.
- [x] Interactive parity pass on a real desktop (Wayland/XWayland, DISPLAY :0): all 24 screens
      toured + rendered, all 4 home modes (Index/ELS/Jog/DRO), keypad popup, plot canvas; servo
      values read live from the board (720/120), nmcli live, non-Pi system detection. v0.1.0.
- [x] Live-motion check (servo jog + index) HW-verified through the UI: jog ramps servo pos,
      index counts stepsToGo to 0 and completes; servo bar shows enabled + live position.
      Fixed a port bug found here — servo mode command was reverted by the laggy `sta` read
      (async write lag); now held until the board confirms it (commit e1a1dc5).

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
