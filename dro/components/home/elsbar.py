from kivy.factory import Factory
from kivy.logger import Logger
from kivy.properties import StringProperty, ObjectProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from pydantic import BaseModel

from dro import feeds
from dro.dispatchers.saving_dispatcher import SavingDispatcher
from dro.utils.kv_loader import load_kv


class FeedMode(BaseModel):
    id: int
    name: str

log = Logger.getChild(__name__)
load_kv(__file__)


class ElsBar(BoxLayout, SavingDispatcher):
    feed_button = ObjectProperty(None)
    feed_ratio = ObjectProperty(None)

    mode_name = StringProperty(":(")
    feed_name = StringProperty(":(")
    current_feeds_index = NumericProperty(0)
    # Hand of the thread / direction of the powered feed: +1 = right-hand, -1 = left-hand.
    # Applied as the sign of the sync ratio pushed to the spindle axis, which reverses the
    # carriage travel per spindle revolution (see set_feed_direction).
    feed_direction = NumericProperty(1)

    _skip_save = [
        "position",
        "x", "y",
        "minimum_width",
        "minimum_height",
        "width", "height",
    ]

    def __init__(self, **kwargs):
        from dro.app import MainApp
        self.app: MainApp = MainApp.get_running_app()
        super().__init__(**kwargs)
        if not self.mode_name in feeds.table.keys():
            self.mode_name = next(iter(feeds.table.keys()))
        self.current_feeds_table = feeds.table[self.mode_name]
        # Magnitude of the feed currently in force, kept so a direction flip can re-push it
        # without going back to the table (which would discard a custom feed).
        self._feed_ratio = None
        self.update_feeds_ratio(self, None)
        self.bind(current_feeds_index=self.update_feeds_ratio)
        self.bind(feed_direction=self._reapply_feed_ratio)

    def update_current_position(self):
        Factory.Keypad().show_with_callback(self.app.servo.set_current_position, self.app.servo.scaledPosition)

    def toggle_servo(self):
        """Enable/disable the servo output and the spindle sync together.

        In ELS the servo runs in sync mode (servo.mode 1 = sync+index) and follows the
        spindle encoder — but only if the spindle input has sync enabled. The ELS page has
        no sync control of its own, so tie it to the enable button: turning the servo on
        also arms the spindle as the sync source (and turning it off disarms it). This makes
        ELS work from this page alone, without first enabling the spindle from the Jog/DRO page.
        """
        self.app.servo.toggle_enable()
        spindle_axis = self.app.board.get_spindle_axis()
        if spindle_axis is None:
            return
        want_sync = self.app.servo.servoEnable != 0
        if bool(spindle_axis.syncEnable) != want_sync:
            spindle_axis.toggle_sync()

    def set_feed_ratio(self, table_name, index):
        table_instance = feeds.table[table_name]
        self.mode_name = table_name
        self.current_feeds_table = table_instance
        self.current_feeds_index = index

    # ── feed ratio application ───────────────────────────────────────
    @property
    def direction_sign(self) -> int:
        """feed_direction normalised to +1 (right-hand) or -1 (left-hand)."""
        return -1 if self.feed_direction < 0 else 1

    def _push_feed_ratio(self, ratio):
        """Push `ratio` (leadscrew mm per spindle revolution) to the spindle axis, signed
        by the selected hand.

        Fraction keeps the sign on the numerator with the denominator positive, so a
        left-hand selection reaches the board as a negative `scales.num` — which reverses
        the carriage travel per spindle revolution and cuts the opposite hand.
        """
        self._feed_ratio = ratio
        spindle_axis = self.app.board.get_spindle_axis()
        if spindle_axis is None:
            return
        signed = ratio * self.direction_sign
        spindle_axis.syncRatioNum = signed.numerator
        spindle_axis.syncRatioDen = signed.denominator

    def _reapply_feed_ratio(self, *args):
        """Re-push the feed in force after a direction change.

        Uses the cached magnitude rather than the table entry so flipping the hand while a
        custom feed is active doesn't silently revert to the table pick at current_feeds_index.
        """
        if self._feed_ratio is None:
            return
        self._push_feed_ratio(self._feed_ratio)
        log.info(f"Feed direction: {'LH' if self.direction_sign < 0 else 'RH'}")

    def set_feed_direction(self, direction: int):
        """Select right-hand (+1) or left-hand (-1) travel.

        Refused while the servo is running: the sync is incremental so the carriage won't
        jump, but it would reverse into the work mid-cut. The ELS bar also disables the
        control in that state; this is the belt-and-braces check for other callers.
        """
        if self.app.servo.servoEnable != 0:
            log.warning("Refusing to change feed direction while the servo is enabled")
            return
        self.feed_direction = -1 if direction < 0 else 1

    def toggle_feed_direction(self):
        self.set_feed_direction(-self.direction_sign)

    def set_custom_feed(self, table_name, feed_config):
        """Apply a user-entered arbitrary feed ratio that isn't in the configured tables.

        Bypasses the table[index] lookup: the ratio/name come straight from feed_config.
        `feed_config.ratio` is leadscrew mm per spindle revolution, applied to the spindle
        the same way update_feeds_ratio does for a table pick.
        """
        self.mode_name = table_name
        self.current_feeds_table = feeds.table[table_name]
        # Keep the index valid for the (possibly shorter) selected table so a later
        # next/previous_feed can't index out of range.
        if self.current_feeds_index >= len(self.current_feeds_table):
            self.current_feeds_index = len(self.current_feeds_table) - 1
        self._push_feed_ratio(feed_config.ratio)
        self.feed_name = feed_config.name
        log.info(f"Custom feed {table_name}: {feed_config.name} -> "
                 f"{feed_config.ratio.numerator}/{feed_config.ratio.denominator} "
                 f"({'LH' if self.direction_sign < 0 else 'RH'})")

    def update_feeds_ratio(self, instance, value):
        ratio = self.current_feeds_table[self.current_feeds_index].ratio
        self._push_feed_ratio(ratio)
        self.feed_name = self.current_feeds_table[self.current_feeds_index].name
        log.info(f"Configured ratio is: {ratio.numerator}/{ratio.denominator} "
                 f"({'LH' if self.direction_sign < 0 else 'RH'})")

    def next_feed(self):
        if self.current_feeds_index < len(self.current_feeds_table) -1:
            self.current_feeds_index = (self.current_feeds_index + 1)

    def previous_feed(self):
        if self.current_feeds_index > 0:
            self.current_feeds_index = (self.current_feeds_index - 1)