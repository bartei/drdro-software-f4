from kivy.logger import Logger
from kivy.properties import ObjectProperty
from kivy.uix.screenmanager import Screen

from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)


class InputScreen(Screen):
    input = ObjectProperty()
