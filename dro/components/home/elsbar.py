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
        self.update_feeds_ratio(self, None)
        self.bind(current_feeds_index=self.update_feeds_ratio)

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

    def update_feeds_ratio(self, instance, value):
        ratio = self.current_feeds_table[self.current_feeds_index].ratio
        spindle_axis = self.app.board.get_spindle_axis()
        if spindle_axis is not None:
            spindle_axis.syncRatioNum = ratio.numerator
            spindle_axis.syncRatioDen = ratio.denominator
        self.feed_name = self.current_feeds_table[self.current_feeds_index].name
        log.info(f"Configured ratio is: {ratio.numerator}/{ratio.denominator}")

    def next_feed(self):
        if self.current_feeds_index < len(self.current_feeds_table) -1:
            self.current_feeds_index = (self.current_feeds_index + 1)

    def previous_feed(self):
        if self.current_feeds_index > 0:
            self.current_feeds_index = (self.current_feeds_index - 1)