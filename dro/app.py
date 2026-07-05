import os

from kivy.app import App
from kivy.config import Config
from kivy.resources import resource_add_path
from kivy.properties import ObjectProperty, ConfigParserProperty, NumericProperty, ListProperty, StringProperty, BooleanProperty
from kivy.logger import Logger
log = Logger.getChild(__name__)

# Resolve "fonts/…", "pictures/…", "sounds/…" relative to the package, independent of CWD.
resource_add_path(os.path.dirname(__file__))

from dro.components.appsettings import config
from dro.dispatchers.axis import AxisDispatcher
from dro.dispatchers.board import Board
from dro.dispatchers.els import ElsDispatcher
from dro.dispatchers.formats import FormatsDispatcher
from dro.dispatchers.input import InputDispatcher
from dro.dispatchers.servo import ServoDispatcher


class MainApp(App):
    display_color = ConfigParserProperty(
        defaultvalue="#ffffffff",
        section="formatting",
        key="display_color",
        config=config,
    )

    formats = ObjectProperty()
    abs_inc = ConfigParserProperty(
        defaultvalue="ABS", section="global", key="abs_inc", config=config, val_type=str
    )
    currentOffset = NumericProperty(0)
    abs_mode = BooleanProperty(False)

    tool = NumericProperty(0)

    board = ObjectProperty()

    home = ObjectProperty()

    servo: ServoDispatcher = ObjectProperty()

    inputs: list[InputDispatcher] = ListProperty()

    # Backward compat alias for KV files that reference app.scales
    scales: list[InputDispatcher] = ListProperty()

    axes: list[AxisDispatcher] = ListProperty()

    els: ElsDispatcher = ObjectProperty()

    current_mode = ConfigParserProperty(
        defaultvalue=1, section="device", key="current_mode", config=config, val_type=int
    )

    scales_count = ConfigParserProperty(
        defaultvalue=4, section="device", key="scales_count", config=config, val_type=int
    )

    manager = ObjectProperty()

    version = StringProperty()

    def __init__(self, **kv):
        super().__init__(**kv)
        # Lazy-loaded by beep(): None = not tried yet, False = unavailable (logged once).
        self.sound = None

    def beep(self, *args, **kv):
        if self.sound is False:
            return
        if self.sound is None:
            from kivy.core.audio import SoundLoader
            from kivy.resources import resource_find
            self.sound = SoundLoader.load(resource_find("sounds/beep.mp3")) or False
            if self.sound is False:
                log.error("beep: no audio provider could load sounds/beep.mp3")
                return
        self.sound.volume = self.formats.volume
        self.sound.play()

    @staticmethod
    def load_help(help_file_name):
        """
        Loads the specified help file text from the help files folder.
        Looks for .rst files first, falling back to the original filename.
        """
        help_dir = os.path.join(os.path.dirname(__file__), "help")

        # Prefer .rst version of the file
        rst_name = help_file_name.rsplit(".", 1)[0] + ".rst"
        rst_path = os.path.join(help_dir, rst_name)
        if os.path.exists(rst_path):
            with open(rst_path, "r") as f:
                return f.read()

        # Fall back to original filename
        help_file_path = os.path.join(help_dir, help_file_name)
        if not os.path.exists(help_file_path):
            return "Help file not found"

        with open(help_file_path, "r") as f:
            return f.read()

    def set_mode(self, mode_id: int):
        self.current_mode = mode_id

    def get_spindle_axis(self):
        return self.board.get_spindle_axis()

    def build(self):
        self.formats = FormatsDispatcher(id_override="0")
        serial_port = config.getdefault("device", "serial_port", "/dev/serial0")
        baudrate = int(config.getdefault("device", "baudrate", 115200))
        self.board = Board(
            formats=self.formats, offset_provider=self,
            port=serial_port, baudrate=baudrate,
        )

        # Backward compat aliases — most KV files use app.servo / app.inputs / app.axes
        self.servo = self.board.servo
        self.inputs = list(self.board.inputs)
        self.scales = list(self.board.inputs)  # backward compat alias
        self.axes = list(self.board.axes)

        self.els = ElsDispatcher(id_override="0")

        import importlib.metadata
        self.version = "v" + importlib.metadata.version("drdro-software")

        self._apply_mouse_cursor()
        self.formats.bind(hide_mouse_cursor=lambda *_: self._apply_mouse_cursor())

        from dro.components.manager import Manager
        self.manager = Manager()

        # Start the RS-485 poll loop on the running asyncio loop (we run under async_run).
        self.board.start()

        return self.manager

    def _apply_mouse_cursor(self):
        if self.formats.hide_mouse_cursor:
            Config.set('graphics', 'show_cursor', '0')
        else:
            Config.set('graphics', 'show_cursor', '1')
        from kivy.core.window import Window
        Window.show_cursor = not self.formats.hide_mouse_cursor
