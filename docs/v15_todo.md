# v1.5 Board Integration — todo (see v15_design.md for detail)

## Phase 0 — prep
- [x] Merge `main` fixes into `dev`; reconcile branches
- [x] Analyze POC vs current (transport / update / app-UI clusters)
- [x] Confirm scope = Half 1 (runtime) only
- [x] Write `v15_design.md` + `v15_todo.md`

## Phase 1 — transport layer
- [x] Port `dro/comms/tcp_transport.py` (new)
- [x] Port `dro/comms/discovery.py` (new)
- [x] Cherry-pick TCP plumbing onto hardened `dro/comms/protocol_client.py`
- [x] Confirm line-noise guards preserved in `protocol_client.py`
- [x] Unit tests: `TcpTransport` (loopback socket)
- [x] Unit tests: `discovery.probe` / `local_scan_hosts`

## Phase 2 — board driver
- [x] Add `transport`/`host`/`tcp_port` kwargs to `Board.__init__`
- [x] Add `reconfigure()` + `set_poll_period()`
- [x] Adopt lazy-open/retry loop + `_handle_link_error`
- [x] Add `scale_count` property + `_apply_scale_count()`
- [x] Keep `SCALES_COUNT = 4`; add comment
- [x] Unit tests: reconfigure serial↔tcp
- [x] Unit tests: dynamic scale count 4/5/absent

## Phase 3 — app wiring & connection UI
- [x] `app.py`: `[device]` transport block, default serial (+ migrate absent-key)
- [x] `app.py`: `_sync_input_aliases` + `board.bind(inputs=…)`
- [x] `manager.py`: register `ConnectionScreen`
- [x] Port `connection_screen.py` + `.kv` (new)
- [x] `setup_screen.kv`: add "Connection" button (keep "Firmware")
- [x] Unit test: fresh-config resolves to serial
- [x] In-app build smoke: all screens instantiate, transport=serial default

## Phase 4 — responsive home bars
- [x] Port `coordbar.kv` + `dro_coordbar.kv` responsive caps
- [x] Port `dro_mode_layout.py` + `index_mode_layout.py` spacer
- [x] Verify grow/shrink + spacer/servobar pinning (in-app smoke; mock-GL can't build widgets in pytest)

## Phase 5 — verification & back-compat guards
- [ ] Full `uv run pytest` green
- [ ] Grep clean: no import of Half-2 modules
- [ ] `git diff` clean on ignore-list files
- [ ] Bench gate (user): v1.0 serial + v1.5 TCP/discovery/5-axis
