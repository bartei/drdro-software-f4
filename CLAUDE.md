# CLAUDE.md — drDRO Software (drdro-software-f4)

## Project overview

Kivy-based DRO / single-axis controller UI for the drDRO rotary-controller board (STM32F411).
A 1:1 feature port of **rotary-controller-python (RCP)** with the driver layer swapped from
**Modbus RTU** to the firmware's **custom RS-485 line protocol**, board-stored settings, and
firmware updates over the bus. Target platforms: Raspberry Pi (primary), Linux, Windows, macOS.

> **Read `docs/migration_design.md` first** (verbose design) and `docs/migration_todo.md`
> (phased tracker). Firmware/protocol truth: `../drdro-firmware-f4/docs/protocol_design.md`,
> `dualbank_design.md`, `shared/Settings.h`, `tools/dro_update.py`.

## Build and run

```bash
uv sync
uv run python -m dro.main
uv run pytest
uv build
```

## Coding standards (carried over from RCP)

- **Python 3.10+** — modern syntax (`list[X]`, `X | Y`).
- **Naming:** snake_case for functions/vars, PascalCase for classes. **Exception:** properties
  that mirror firmware fields keep firmware naming for cross-reference; protocol variable names
  are dotted (`scales.num`, `servo.max`).
- **Imports:** stdlib, third-party, local; absolute (`from dro.comms.protocol_client import ...`).
- **Logging:** Kivy's logger — `from kivy.logger import Logger` then `log = Logger.getChild(__name__)`.
  Do **not** use loguru or `from kivy import Logger`. Log exceptions with `log.exception()` /
  `log.error(f"...: {e}")`; use `str(e)`, never `e.__str__()`.
- **Exceptions:** catch specific types; no empty `except: pass`; raise proper types.
- **KV loading:** module-level companion `.kv` load (see `utils/kv_loader.py`).
- **Persistence:** `SavingDispatcher` auto-persists Kivy properties to YAML under
  `~/.config/` ; `_skip_save` / `_force_save` lists; `id_override` for multiple instances.

## Driver layer (the key difference from RCP)

- Communication is the firmware **line protocol**, not Modbus. One device, no addressing,
  115200, RS-485 auto-direction. Request `cmd args[*HH]\n`; response `key=value\n…crc=HH\n\n`
  (XOR-8). Client lives in `dro/comms/protocol_client.py`.
- Variable access is by **dotted name** (`client.set('servo.max', v)` / `client.get(...)`),
  not register address. See the registry + mapping table in `docs/migration_design.md` §C.3.
- **Settings:** prefer board-stored values (`save`/`load`/`settings`) over re-pushing on
  reconnect — see §D of the design doc for what lives on the board vs. the host.

## Git & releases

- Branches: `main` (releases) / `dev` (pre-releases); conventional commits;
  `python-semantic-release`. **No AI/Claude attribution in commits or PRs.**

## Time tracking

- When a task is completed and recorded in a Jira ticket, also log the time spent as a Jira
  worklog on that ticket. If exact time isn't known, propose an estimate before logging.
