"""Home-page banner shown when the connected board's firmware is older than the companion
version this software needs (dro.utils.fw_compat). Tapping it opens the firmware screen,
where the user can pick a suitable online release and OTA-update over RS-485."""
from kivy.logger import Logger
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout

from dro.utils.fw_compat import COMPANION_FW_VERSION
from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)


class FirmwareUpdateBanner(ButtonBehavior, BoxLayout):
    show = BooleanProperty(False)
    board_version = StringProperty("")
    required_version = StringProperty(COMPANION_FW_VERSION)

    def __init__(self, **kv):
        from dro.app import MainApp
        self.app: MainApp = MainApp.get_running_app()
        super().__init__(**kv)
        self.app.board.bind(
            connected=self._refresh,
            firmware_version=self._refresh,
            firmware_update_required=self._refresh,
        )
        self._refresh()

    def _refresh(self, *args):
        board = self.app.board
        self.board_version = board.firmware_version
        self.show = bool(board.connected and board.firmware_update_required)

    def on_release(self):
        self.app.manager.goto("firmware")