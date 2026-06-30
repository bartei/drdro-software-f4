from kivy.logger import Logger
from kivy.properties import StringProperty, BooleanProperty
from dro.components.popups.help_popup import HelpPopup  # noqa: F401
from kivy.uix.boxlayout import BoxLayout

from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)


class StringItem(BoxLayout):
    name = StringProperty("")
    value = StringProperty("")
    disabled = BooleanProperty(False)
    help_file = StringProperty("")
