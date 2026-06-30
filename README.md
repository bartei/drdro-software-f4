# drDRO Software (drdro-software-f4)

A **Kivy-based Digital Read-Out (DRO) and single-axis controller UI** for rotary tables,
running on Raspberry Pi or desktop (Linux/Windows/macOS). It drives the **drDRO**
STM32F411 control board ([drdro-firmware-f4](https://github.com/bartei/drdro-firmware-f4))
over RS-485 using the firmware's **custom CLI line protocol** (replacing the older Modbus
RTU stack).

This is the successor to **rotary-controller-python (RCP)** — a 1:1 feature port with the
driver layer swapped to the new protocol, board-side persistent settings, and firmware
updates driven over the same RS-485 bus.

> **This repo is in migration setup.** See `docs/migration_design.md` (verbose design) and
> `docs/migration_todo.md` (phased tracker). Implementation begins after the design review.

---

## Features (target — ported 1:1 from RCP)

- Responsive touch UI built with **Kivy**.
- Communicates over **RS-485** with the drDRO board via its line protocol (115200, auto-direction).
- **Configurable axes** — assign hardware scale inputs, apply transforms (identity / sum).
- **Electronic Lead Screw (ELS)** mode for synchronized threading and power feed.
- **Sync mode** with configurable gear ratios for spindle-synchronized movement.
- **Indexing / Jog / DRO** operating modes; pattern calculators (circle / line / rect).
- Customizable display: fonts, colors, metric/imperial/angle formats.
- Contextual RST help on every setting; WiFi (nmcli) and Pi system maintenance screens.
- **New:** STM32 **firmware update + bank management** over RS-485 (YMODEM), and reliance on
  **board-stored settings** instead of re-pushing config on every reconnect.

---

## Requirements

- **Hardware:** drDRO controller board (firmware: `drdro-firmware-f4`), RS-485 interface,
  Raspberry Pi 3/4/5 for Pi deployments.
- **Software:** Python 3.10+, [`uv`](https://docs.astral.sh/uv/).

## Build & run

```bash
uv sync                       # install dependencies
uv run python -m dro.main     # run the app
uv run pytest                 # run tests
uv build                      # build package
```

---

## Project structure (target)

```
dro/
├── main.py                 # Entry point (asyncio + Kivy event loop)
├── app.py                  # MainApp
├── feeds.py                # Feed/thread pitch tables
├── comms/                  # RS-485 line-protocol driver (replaces Modbus)
│   ├── protocol_client.py  # Framed request/response client (get/set/sta/save/load/...)
│   ├── ymodem.py           # YMODEM sender (firmware push)
│   └── updater.py          # Firmware update + bank management orchestration
├── dispatchers/            # Event dispatchers & state (board, axis, input, servo, els, formats, ...)
├── components/             # UI (screens, home/mode bars, popups, widgets, plot, toolbars)
└── utils/                  # platform.py, kv_loader.py, ctype_calc.py
```

---

## References

- **Firmware & protocol:** [drdro-firmware-f4](https://github.com/bartei/drdro-firmware-f4)
  (`docs/protocol_design.md`, `dualbank_design.md`, `tools/dro_update.py`).
- **Predecessor:** [rotary-controller-python](https://github.com/bartei/rotary-controller-python).

## License

MIT. See `LICENSE`.
