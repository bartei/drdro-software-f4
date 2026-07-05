"""Approach beeper — the audible half of the PT 855 graphic positioning aid (G2).

As an armed axis nears its target the beeps get faster AND higher-pitched (parking-sensor
style); on arrival a solid tone sounds for ~1 s and then goes silent so it doesn't nag the
operator while parked. It re-arms only when the axis leaves and re-enters the tolerance window.
Everything is synthesized on the fly (see dro.utils.tone) — no audio assets.
"""
from kivy.clock import Clock
from kivy.logger import Logger

from dro.utils import tone

log = Logger.getChild(__name__)

# Pitch + cadence endpoints: 'far' = at the edge of the positioning range, 'near' = at tolerance.
FAR_FREQ = 600.0
NEAR_FREQ = 1400.0
FAR_INTERVAL = 0.6      # seconds between beeps at the far edge of the window
NEAR_INTERVAL = 0.08    # seconds between beeps just before arrival
BEEP_MS = 70
FREQ_STEP = 25.0        # quantize pitch so the tone cache stays small

ARRIVE_FREQ = 1500.0
ARRIVE_MS = 1000        # solid "you're there" tone, then silence (per operator request)

TICK = 1 / 30.0


class ApproachBeeper:
    """Polls the armed axes and drives the tone synthesizer. Owned by the app; start()/stop()."""

    def __init__(self, app):
        self.app = app
        self._accum = 0.0            # time since the last approach beep
        self._interval = FAR_INTERVAL
        self._arrived_axis = None    # axis latched as 'arrived' (chimed once, now silent)
        self._event = None

    def start(self):
        if self._event is None:
            # Pre-generate the long arrival tone so the first arrival doesn't hitch the UI.
            tone.get_tone(ARRIVE_FREQ, ARRIVE_MS)
            self._event = Clock.schedule_interval(self._tick, TICK)

    def stop(self):
        if self._event is not None:
            self._event.cancel()
            self._event = None

    def _dtg_mm(self, axis, factor):
        # distanceToGo is in display units; tolerance/range are stored in mm. Work in mm so the
        # cue's physical window is unit-independent (matches the graphic aid).
        d = abs(axis.distanceToGo)
        return d / factor if factor else d

    def _tick(self, dt):
        fmt = self.app.formats
        if not getattr(fmt, "beep_on_approach", True) or fmt.volume <= 0:
            return
        span = float(fmt.positioning_range) or 1.0     # mm
        factor = float(fmt.factor)
        axes = [a for a in getattr(self.app, "axes", [])
                if getattr(a, "target_active", False) and not a.spindleMode]
        if not axes:
            self._reset()
            return

        def dmm(a):
            return self._dtg_mm(a, factor)

        def tol(a):
            return float(a.position_tolerance)          # mm

        approaching = [a for a in axes if tol(a) < dmm(a) <= span]
        arrived = [a for a in axes if dmm(a) <= tol(a)]

        if approaching:
            # Cue the axis you're closest to landing; moving again re-arms the arrival chime.
            focus = min(approaching, key=dmm)
            self._arrived_axis = None
            self._approach(dt, dmm(focus), span, tol(focus), fmt.volume)
        elif arrived:
            focus = min(arrived, key=dmm)
            if self._arrived_axis is not focus:
                self._arrived_axis = focus
                tone.play_tone(ARRIVE_FREQ, ARRIVE_MS, fmt.volume)  # ~1 s solid, then silence
            self._accum = 0.0
        else:
            # Armed but still outside the approach window — quiet, ready for the next approach.
            self._accum = 0.0
            self._interval = FAR_INTERVAL

    def _approach(self, dt, d, span, tol, volume):
        rng = max(1e-9, span - tol)
        f = max(0.0, min(1.0, (d - tol) / rng))   # 1 at the far edge, 0 at tolerance
        near = 1.0 - f
        freq = round((FAR_FREQ + (NEAR_FREQ - FAR_FREQ) * near) / FREQ_STEP) * FREQ_STEP
        self._interval = FAR_INTERVAL + (NEAR_INTERVAL - FAR_INTERVAL) * near
        self._accum += dt
        if self._accum >= self._interval:
            self._accum = 0.0
            tone.play_tone(freq, BEEP_MS, volume)

    def _reset(self):
        self._accum = 0.0
        self._interval = FAR_INTERVAL
        self._arrived_axis = None
