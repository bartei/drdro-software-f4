import os

from kivy.logger import Logger
from kivy.properties import StringProperty, NumericProperty, ListProperty
from kivy.uix.screenmanager import Screen

from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)

VISIBLE_LINES = 30


class LogViewerScreen(Screen):
    log_file_path = StringProperty("")
    log_file_name = StringProperty("Log Viewer")
    log_content = StringProperty("")
    line_count = NumericProperty(0)
    slider_value = NumericProperty(0)

    _lines: list[str] = []

    def load_file(self, path: str):
        self.log_file_path = path
        self.log_file_name = os.path.basename(path)
        try:
            with open(path, "r") as f:
                self._lines = f.readlines()
        except OSError as e:
            self._lines = [f"Error reading log file: {e}"]

        self.line_count = len(self._lines)
        # Start at the end of the file (most recent logs)
        self.slider_value = max(0, self.line_count - VISIBLE_LINES)
        self._update_view()

    def on_slider_value(self, instance, value):
        self._update_view()

    def _update_view(self):
        start = int(self.slider_value)
        end = start + VISIBLE_LINES
        visible = self._lines[start:end]
        self.log_content = "".join(visible)