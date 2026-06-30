"""Board dispatcher — owns the RS-485 line-protocol link and bridges it to the Kivy UI.

Replaces the Modbus `ConnectionManager`/`device[...]` register model with the async
`ProtocolClient` (dro.comms). The bridge between the synchronous Kivy/dispatcher world and
the async client:

- A single **async poll loop** (`run`) issues `sta` at ~30 Hz, maps the reply into
  `fast_data_values` (keeping the field names the dispatchers already use), bumps the
  `update_tick` Kivy property, and tracks `connected`. Low-rate `diag.*` is folded in.
- Synchronous dispatcher callbacks issue writes via `write()` / `write_persisted()`, which
  schedule the async `set` (and a debounced `save`) on the running loop — never blocking.
- On (re)connect the board reads the full `settings` dump into a cache; `cached()` serves the
  occasional synchronous reads (e.g. sync-enable state) the dispatchers need.

Settings model (design §D): the firmware is the source of truth for `servo.max/acc/jog`
(read on connect, `set`+`save` on UI change); dynamic ratios `scales.num/den` are pushed
live and never saved; `scales.sync`/`servo.mode` are live operational state.
"""
import asyncio
import os
import time

from kivy.clock import Clock
from kivy.event import EventDispatcher
from kivy.properties import NumericProperty, BooleanProperty, ObjectProperty, ListProperty

from dro.comms.protocol_client import ProtocolClient, Response
from dro.dispatchers.axis import AxisDispatcher
from dro.dispatchers.axis_transform import AxisTransform
from dro.dispatchers.input import InputDispatcher
from dro.dispatchers.saving_dispatcher import SETTINGS_FOLDER, read_settings
from dro.dispatchers.servo import ServoDispatcher
from dro.utils.constants import SCALES_COUNT

from kivy.logger import Logger
log = Logger.getChild(__name__)


def map_sta(resp: Response) -> dict:
    """Map an `sta` response to the legacy `fast_data_values` dict the dispatchers consume.

    Keeps the old field names so the dispatcher tick handlers port unchanged:
      scaleCurrent/scaleSpeed (4-arrays), servoCurrent, servoSpeed, stepsToGo, servoEnable.
    (`servoEnable` is the firmware's 0/1/2 servoMode — identical semantics.)
    """
    return {
        "scaleCurrent": resp.as_ints("scales.pos") or [0] * SCALES_COUNT,
        "scaleSpeed": resp.as_ints("scales.speed") or [0] * SCALES_COUNT,
        "servoCurrent": resp.as_int("servo.pos") or 0,
        "servoSpeed": resp.as_float("servo.speed") or 0.0,
        "stepsToGo": resp.as_int("servo.tgt") or 0,
        "servoEnable": resp.as_int("servo.mode") or 0,
    }


class Board(EventDispatcher):
    connected = BooleanProperty(False)
    update_tick = NumericProperty(0)
    blink = BooleanProperty(False)
    servo = ObjectProperty(None, allownone=True)
    inputs = ListProperty()
    axes = ListProperty()

    def __init__(self, formats, offset_provider, *, port="/dev/serial0", baudrate=115200,
                 poll_period=1.0 / 50, save_debounce=0.75, **kv):
        super().__init__(**kv)
        self.formats = formats
        self.offset_provider = offset_provider
        self.fast_data_values = dict()

        self.connection = ProtocolClient(port, baudrate=baudrate)
        self._poll_period = poll_period
        self._save_debounce = save_debounce

        self._settings: Response | None = None        # last `settings` snapshot (cache)
        self._running = False
        self._paused = False                           # firmware update yields the bus
        self.comm_rate = 0.0                           # measured `sta` polls/sec (EMA)
        self._last_poll_t: float | None = None
        self.firmware_version = ""                     # cached on connect (for the Stats screen)
        # Diag (`diag.cycles`/`diag.interval`) is only polled when something displays it —
        # the top ribbon or the Stats screen — so a normal session does no extra round-trips.
        self.ribbon_visible = False
        self.stats_active = False
        self.diag_cycles = 0                           # last diag.cycles / diag.interval
        self.diag_interval = 0                         # (kept separate so sta polls don't wipe them)
        self._diag_counter = 0
        self._save_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

        self.servo = ServoDispatcher(board=self, formats=formats, id_override="0")
        for i in range(SCALES_COUNT):
            self.inputs.append(InputDispatcher(
                board=self, inputIndex=i, id_override=f"{i}",
            ))

        self._create_axes()

        Clock.schedule_interval(self.blinker, 1.0 / 4)

    # ── async link lifecycle ─────────────────────────────────────────
    async def open(self) -> None:
        await self.connection.open()

    def start(self, *, period: float | None = None) -> None:
        """Start the poll loop on the running asyncio loop (call after the loop is up)."""
        if self._running:
            return
        self._running = True
        self._spawn(self.run(period or self._poll_period))

    async def run(self, period: float) -> None:
        await self.open()
        while self._running:
            t0 = time.monotonic()
            await self.poll_once()
            # Rate-limit to `period` by sleeping only the remainder after the sta round-trip,
            # rather than adding a fixed sleep on top of it (which capped us well below target).
            await asyncio.sleep(max(0.0, period - (time.monotonic() - t0)))

    def stop(self) -> None:
        self._running = False

    def pause(self) -> None:
        """Stop polling so another task (firmware update) can take exclusive bus ownership."""
        self._paused = True

    def resume(self) -> None:
        """Resume polling; force a settings re-read on the next successful poll."""
        self._settings = None
        self.connected = False
        self._paused = False

    async def poll_once(self) -> None:
        """One poll cycle: `sta` → fast_data_values, connection/cache handling, tick bump."""
        if self._paused:
            return
        was_disconnected = not self.connected
        resp = await self.connection.sta()

        if resp.crc_ok:
            self.fast_data_values = map_sta(resp)
            await self._poll_diag()
            if was_disconnected:
                await self._refresh_settings()      # cache BEFORE flipping connected
            self.connected = True
            self._measure_comm_rate()
        else:
            self.connected = self.connection.connected

        if not self.connected:
            self.comm_rate = 0.0
            self._last_poll_t = None

        self.update_tick = (self.update_tick + 1) % 100

    def _measure_comm_rate(self) -> None:
        """Update the EMA of the achieved `sta` poll frequency (Hz) for the status bar."""
        now = time.monotonic()
        if self._last_poll_t is not None:
            dt = now - self._last_poll_t
            if dt > 0:
                inst = 1.0 / dt
                self.comm_rate = inst if self.comm_rate <= 0 else self.comm_rate * 0.8 + inst * 0.2
        self._last_poll_t = now

    async def _poll_diag(self) -> None:
        """Low-rate diag read (statusbar) — ~once per second, folded into the poll loop.
        Skipped entirely unless the ribbon or Stats screen is showing it."""
        if not (self.ribbon_visible or self.stats_active):
            return
        self._diag_counter += 1
        if self._diag_counter * self._poll_period < 1.0:
            return
        self._diag_counter = 0
        rc = await self.connection.get("diag.cycles")
        if rc.crc_ok:
            self.diag_cycles = rc.as_int("diag.cycles") or 0
        ri = await self.connection.get("diag.interval")
        if ri.crc_ok:
            self.diag_interval = ri.as_int("diag.interval") or 0

    async def _refresh_settings(self) -> None:
        r = await self.connection.settings()
        if r.crc_ok:
            self._settings = r
            log.info("Loaded board settings snapshot (%d vars)", len(r.values))
        v = await self.connection.command("version")
        if v.crc_ok and v.text("version"):
            self.firmware_version = v.text("version")

    # ── write / read facade used by the dispatchers ─────────────────
    def write(self, name: str, value, idx: int | None = None) -> None:
        """Fire-and-forget live `set` (no flash save). No-op when disconnected."""
        if not self.connected:
            return
        self._spawn(self.connection.set(name, value, idx))

    def write_persisted(self, name: str, value, idx: int | None = None) -> None:
        """Live `set` + debounced flash `save` — for board-owned settings on UI change."""
        if not self.connected:
            return
        self._spawn(self._set_then_save(name, value, idx))

    async def _set_then_save(self, name: str, value, idx: int | None) -> None:
        await self.connection.set(name, value, idx)
        self._schedule_save()

    def _schedule_save(self) -> None:
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
        self._save_task = self._spawn(self._debounced_save())

    async def _debounced_save(self) -> None:
        try:
            await asyncio.sleep(self._save_debounce)
        except asyncio.CancelledError:
            return
        r = await self.connection.save()
        if r:
            log.info("Settings saved to board flash")
        else:
            log.warning("Settings save failed: %s", r.error)

    def cached(self, name: str, idx: int | None = None) -> str | None:
        """Read a value from the last `settings` snapshot (synchronous, for the UI thread)."""
        if self._settings is None:
            return None
        if idx is None:
            return self._settings.text(name)
        raw = self._settings.values.get(name)
        if not raw:
            return None
        parts = raw.split(",")
        return parts[idx] if idx < len(parts) else None

    # ── task bookkeeping ─────────────────────────────────────────────
    def _spawn(self, coro) -> asyncio.Task | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.error("No running asyncio loop; dropping coroutine %r", coro)
            coro.close()
            return None
        task = loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ── axes management (ported from RCP) ────────────────────────────
    def _create_axes(self):
        """Create AxisDispatchers, migrating from input configs if no Axis YAMLs exist."""
        axis_files = sorted(SETTINGS_FOLDER.glob("Axis-*.yaml")) if SETTINGS_FOLDER.exists() else []

        max_id = -1
        if axis_files:
            for f in axis_files:
                axis_id = f.stem.replace("Axis-", "")
                try:
                    max_id = max(max_id, int(axis_id))
                except ValueError:
                    pass
                ax = AxisDispatcher(
                    board=self, formats=self.formats, servo=self.servo,
                    offset_provider=self.offset_provider,
                    inputs=list(self.inputs),
                    id_override=axis_id,
                )
                self.axes.append(ax)
        else:
            log.info("No Axis YAML files found — creating 4 identity axes")
            for i in range(SCALES_COUNT):
                ax = AxisDispatcher(
                    board=self, formats=self.formats, servo=self.servo,
                    offset_provider=self.offset_provider,
                    inputs=list(self.inputs),
                    transform=AxisTransform.identity(i),
                    id_override=f"{i}",
                    axis_name=f"{i}",
                    axis_index=i,
                )
                ax._save_transform_config()
                self.axes.append(ax)
            max_id = SCALES_COUNT - 1

        self._next_axis_id = max_id + 1

    def add_axis(self, transform: AxisTransform | None = None, axis_name: str = "?") -> AxisDispatcher:
        axis_id = self._next_axis_id
        self._next_axis_id += 1

        if transform is None:
            used_inputs = set()
            for ax in self.axes:
                used_inputs |= ax.transform.input_indices
            available = [i for i in range(len(self.inputs)) if i not in used_inputs]
            input_idx = available[0] if available else 0
            transform = AxisTransform.identity(input_idx)

        ax = AxisDispatcher(
            board=self, formats=self.formats, servo=self.servo,
            offset_provider=self.offset_provider,
            inputs=list(self.inputs),
            transform=transform,
            id_override=f"{axis_id}",
            axis_name=axis_name,
            axis_index=len(self.axes),
        )
        ax._save_transform_config()
        self.axes.append(ax)
        return ax

    def remove_axis(self, axis: "AxisDispatcher"):
        try:
            self.axes.remove(axis)
        except ValueError:
            log.warning(f"Axis '{axis.axis_name}' not found in axes list")
            return
        config_file = axis.filename
        if config_file.exists():
            os.remove(config_file)
            log.info(f"Removed axis config: {config_file}")

    def get_spindle_axis(self):
        filtered = [a for a in self.axes if a.spindleMode is True]
        if len(filtered) != 1:
            return None
        return filtered[0]

    def blinker(self, *args):
        self.blink = not self.blink
