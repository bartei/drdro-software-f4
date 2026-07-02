from kivy.logger import Logger
from kivy.properties import StringProperty, NumericProperty
from dro.components.popups.help_popup import HelpPopup  # noqa: F401
from kivy.uix.boxlayout import BoxLayout

from dro.utils import encoder_filter
from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)


class FilterItem(BoxLayout):
    """Encoder input-filter setting: 0-15 value with a live timing info line."""

    name = StringProperty("")
    value = NumericProperty(5)
    info = StringProperty(encoder_filter.describe(5))
    help_file = StringProperty("")

    def validate(self, value):
        try:
            v = int(value)
        except (TypeError, ValueError) as e:
            log.error(f"Invalid filter value {value!r}: {str(e)}")
            return
        self.value = max(0, min(encoder_filter.FILTER_MAX, v))

    def on_value(self, instance, value):
        self.validate(value)
        self.info = encoder_filter.describe(int(self.value))
