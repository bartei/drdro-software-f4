import collections
import time

from fractions import Fraction

from kivy.logger import Logger
from kivy.properties import StringProperty, NumericProperty, BooleanProperty

from dro.dispatchers.saving_dispatcher import SavingDispatcher
from dro.utils.ctype_calc import uint32_subtract_to_int32

log = Logger.getChild(__name__)


class ServoDispatcher(SavingDispatcher):
    _save_class_name = "ServoBar"

    name = StringProperty("R")
    maxSpeed = NumericProperty(1000)
    acceleration = NumericProperty(1000)
    speed = NumericProperty(0)
    jogSpeed = NumericProperty(0)
    ratioNum = NumericProperty(400)
    ratioDen = NumericProperty(360)
    offset = NumericProperty(0.0)
    divisions = NumericProperty(12)
    preferredDirection = NumericProperty(1)
    index = NumericProperty(0)

    servoEnable = NumericProperty(0)
    unitsPerTurn = NumericProperty(360.0)
    oldOffset = NumericProperty(0.0)

    elsMode = BooleanProperty(False)
    leadScrewPitch = NumericProperty(0.25)
    leadScrewPitchIn = BooleanProperty(True)
    leadScrewPitchSteps = BooleanProperty(800)

    position = NumericProperty(0)
    scaledPosition = NumericProperty(0)
    formattedPosition = StringProperty("--")

    indexSpeed = NumericProperty(200)

    disableControls = BooleanProperty(False)

    _skip_save = [
        "update_tick",
        "connected",
        "device",
        "position",
        "scaledPosition",
        "formattedPosition",
        "servoEnable",
        "oldOffset",
        "offset",
        "index",
        "preferredDirection",
        "disableControls",
        "speed",
        "direction",
    ]

    def __init__(self, board, formats, **kv):
        self.board = board
        self.formats = formats
        # Guards write-back to the board while we're syncing FROM board-stored settings.
        self._syncing = False
        super().__init__(**kv)
        self.configure_lead_screw_ratio(self, None)

        # Board event bindings
        self.board.bind(connected=self.on_connected)
        self.board.bind(connected=self.update_positions)
        self.board.bind(update_tick=self.on_update_tick)

        # Property bindings
        self.bind(divisions=self.update_positions)
        self.bind(ratioNum=self.update_positions)
        self.bind(ratioDen=self.update_positions)
        self.bind(ratioNum=self.update_scaledPosition)
        self.bind(ratioDen=self.update_scaledPosition)
        self.bind(position=self.update_scaledPosition)
        self.bind(elsMode=self.update_scaledPosition)
        self.formats.bind(current_format=self.update_scaledPosition)
        self.update_scaledPosition(self, None)

        self.bind(leadScrewPitch=self.configure_lead_screw_ratio)
        self.bind(leadScrewPitchIn=self.configure_lead_screw_ratio)
        self.bind(leadScrewPitchSteps=self.configure_lead_screw_ratio)

        # Private variables that don't need dispatchers etc
        self.encoderPrevious = 0
        self.encoderCurrent = 0
        self.previous_axis_time = time.time()
        self.speed_history = collections.deque(maxlen=4)
        self.previousIndex = 0
        self.step_positions = dict()
        self.positions = dict()
        self.disableControls = True
        self.servoEnable = 0
        self._speed_override_active = False
        # servo.mode is a command the host owns, but `sta` reports it back with poll lag.
        # Track the value we last commanded and don't let the laggy read revert it until
        # the board confirms it (else the async write oscillates against the poll). Once
        # confirmed (or after a timeout), firmware-driven changes (e.g. sync→1) are adopted.
        self._expected_mode: int | None = None
        self._mode_wait = 0
        self._adopting_mode = False

    def configure_lead_screw_ratio(self, instance, value):
        if self.elsMode is True:
            leadScrewPitch = Fraction(self.leadScrewPitch)

            if self.leadScrewPitchIn is True:
                leadScrewPitch = leadScrewPitch * Fraction(254, 10)

            leadScrewRatio = leadScrewPitch * Fraction(1, self.leadScrewPitchSteps)
            self.ratioNum = leadScrewRatio.numerator
            self.ratioDen = leadScrewRatio.denominator

    def _sync_from_board(self):
        """Firmware is the source of truth for servo.max/acc/jog — pull them on connect.

        Suppresses the write-back so syncing the UI to board values doesn't re-`set`+`save`.
        """
        self._syncing = True
        try:
            v = self.board.cached("servo.max")
            if v is not None:
                self.maxSpeed = float(v)
            v = self.board.cached("servo.acc")
            if v is not None:
                self.acceleration = float(v)
            v = self.board.cached("servo.jog")
            if v is not None:
                self.jogSpeed = float(v)
        finally:
            self._syncing = False

    def on_connected(self, instance, value):
        try:
            if self.board.connected:
                self.encoderPrevious = self.board.fast_data_values['servoCurrent']
                self.encoderCurrent = self.board.fast_data_values['servoCurrent']
                self.servoEnable = self.board.fast_data_values['servoEnable']
                self._sync_from_board()

                if self.servoEnable == 0:
                    self.disableControls = True
                else:
                    self.disableControls = False
        except Exception as e:
            log.error(str(e))

    def update_positions(self, *args, **kv):
        ratio = Fraction(self.ratioNum, self.ratioDen)
        if self.divisions < 1:
            self.divisions = 1
        self.positions = dict()
        self.step_positions = dict()
        for i in range(self.divisions):
            self.positions[i] = i * (self.unitsPerTurn / self.divisions)
            self.step_positions[i] = round(self.positions[i] / ratio)

        self.previousIndex = 0
        self.index = 0

    def on_update_tick(self, instance, value):
        try:
            if not self.board.connected:
                return

            self.encoderPrevious = self.encoderCurrent
            self.encoderCurrent = self.board.fast_data_values['servoCurrent']
            self._reconcile_mode(self.board.fast_data_values['servoEnable'])

            steps_per_second = self.board.fast_data_values['servoSpeed']
            self.speed_history.append(steps_per_second)
            speed = sum(self.speed_history) / len(self.speed_history)
            if speed != self.speed:
                self.speed = speed

            delta = uint32_subtract_to_int32(self.encoderCurrent, self.encoderPrevious)
            self.position += delta
            if (
                    self.board.fast_data_values['stepsToGo'] == 0 and
                    self.servoEnable != 0 and
                    self.disableControls
                    and self.board.connected
            ):
                if self._speed_override_active:
                    self.board.write('servo.max', self.maxSpeed)
                    self._speed_override_active = False
                    log.info("Restored maxSpeed to %s", self.maxSpeed)
                log.info("Disable Controls False")
                self.disableControls = False
        except Exception as e:
            log.error(f"Unable to read servo: {str(e)}")

    def update_scaledPosition(self, instance, value):
        ratio = Fraction(self.ratioNum, self.ratioDen)

        if self.elsMode is False and self.unitsPerTurn > 0:
            self.scaledPosition = float(self.position * ratio) % self.unitsPerTurn
            fp = self.formats.angle_format.format(self.scaledPosition)
        else:
            self.scaledPosition = float(self.position * ratio) * self.formats.factor
            fp = self.formats.position_format.format(self.scaledPosition)
        if fp != self.formattedPosition:
            self.formattedPosition = fp

    def go_next(self):
        self.preferredDirection = 1
        self.index = (self.index + 1) % self.divisions

    def go_previous(self):
        self.preferredDirection = -1
        self.index = (self.index - 1) % self.divisions

    def on_index(self, instance, value):
        ratio = Fraction(self.ratioNum, self.ratioDen)
        self.index = self.index % self.divisions

        index_delta = (self.index - self.previousIndex)
        half_divisions = self.divisions // 2
        steps_per_turn = (self.unitsPerTurn / ratio)
        delta = self.step_positions[self.index] - self.step_positions[self.previousIndex]

        if self.preferredDirection > 0:
            if index_delta > half_divisions:
                delta = -(steps_per_turn - delta)
            if index_delta <= -half_divisions:
                delta = (delta + steps_per_turn)

        if self.preferredDirection < 0:
            if index_delta >= half_divisions:
                delta = -(steps_per_turn - delta)
            if index_delta < -half_divisions:
                delta = (delta + steps_per_turn)

        if delta != 0:
            self.board.write('servo.max', self.indexSpeed)
            self._speed_override_active = True
            self.board.write('servo.tgt', delta)
            self.disableControls = True
            self.previousIndex = self.index

    def on_offset(self, instance, value):
        ratio = Fraction(self.ratioNum, self.ratioDen)
        delta = value - self.oldOffset
        delta_steps = int(delta / ratio)
        if delta_steps != 0:
            self.board.write('servo.max', self.indexSpeed)
            self._speed_override_active = True
            self.board.write('servo.tgt', delta_steps)
            self.disableControls = True
            self.oldOffset = value

    def on_maxSpeed(self, instance, value):
        if self._syncing:
            return
        self.board.write_persisted('servo.max', self.maxSpeed)

    def on_jogSpeed(self, instance, value):
        if self._syncing:
            return
        # Live operational value (jogbar slider), NOT a flash-saved config: a `save` here
        # would stall the firmware protocol task for the flash-write time (~200 ms) and freeze
        # the position readout mid-jog. servo.max/acc stay persisted (set in Servo Settings).
        self.board.write('servo.jog', self.jogSpeed)

    def on_acceleration(self, instance, value):
        if self._syncing:
            return
        self.board.write_persisted('servo.acc', self.acceleration)

    def _reconcile_mode(self, board_mode):
        """Sync self.servoEnable with the board's reported servoMode, without fighting a
        command we just issued (write lag) — see _expected_mode."""
        if self._expected_mode is not None:
            if board_mode == self._expected_mode:
                self._expected_mode = None
                self._mode_wait = 0
            else:
                self._mode_wait += 1
                if self._mode_wait > 30:          # ~1 s: command never confirmed, give up
                    self._expected_mode = None
                    self._mode_wait = 0
            return
        if board_mode != self.servoEnable:        # firmware-driven change (e.g. sync→1)
            self._adopting_mode = True
            try:
                self.servoEnable = board_mode
            finally:
                self._adopting_mode = False

    def on_servoEnable(self, instance, value):
        if not self._adopting_mode:               # host-initiated → command the board
            self._expected_mode = int(self.servoEnable)
            self._mode_wait = 0
            self.board.write('servo.mode', self.servoEnable)
        if self.servoEnable != 0:
            log.info("Disable Controls False")
            self.disableControls = False
        else:
            log.info("Disable Controls True")
            self.disableControls = True

    def toggle_enable(self):
        if not self.board.connected:
            self.servoEnable = 0
            return

        if self.servoEnable != 0:
            self.servoEnable = 0
        else:
            self.servoEnable = 1

    def set_current_position(self, value):
        ratio = Fraction(self.ratioNum, self.ratioDen)
        self.position = int(value / ratio)

    def update_current_position(self):
        from dro.components.popups.keypad import Keypad
        keypad = Keypad()
        keypad.show_with_callback(self.set_current_position, self.scaledPosition)
