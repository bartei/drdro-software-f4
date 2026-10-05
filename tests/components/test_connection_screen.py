"""ConnectionScreen logic — config resolution, live apply, and device selection.

Drives the real ConnectionScreen methods on a duck-typed self (its __init__ needs a live app +
KV widget tree), same approach as test_els_feed_direction. The key back-compat rule under test:
a config with no `transport` key resolves to **serial**, so an existing v1.0 install is untouched.
"""
from dro.components.screens import connection_screen as cs
from dro.components.screens.connection_screen import ConnectionScreen


def _cfg(tmp_path):
    """A fresh instance of the app's ConfigParser class, backed by a writable temp file."""
    c = type(cs.config)()
    c.read(str(tmp_path / "config.ini"))     # sets the filename so _save_to_config().write() works
    return c


class _FakeBoard:
    def __init__(self):
        self.reconfigured = None
        self.poll_period = None

    def reconfigure(self, **kw):
        self.reconfigured = kw

    def set_poll_period(self, p):
        self.poll_period = p


class _FakeApp:
    def __init__(self):
        self.board = _FakeBoard()


class _FakeConn:
    """Borrow the real ConnectionScreen logic without building the Kivy widget tree."""
    _load_from_config = ConnectionScreen._load_from_config
    _save_to_config = ConnectionScreen._save_to_config
    on_transport_selected = ConnectionScreen.on_transport_selected
    on_device_selected = ConnectionScreen.on_device_selected
    apply = ConnectionScreen.apply

    def __init__(self):
        self.transport = "serial"
        self.host = ""
        self.tcp_port = 5555
        self.serial_port = "/dev/serial0"
        self.baudrate = 115200
        self.refresh_hz = 50
        self.status_text = ""
        self.ids = {}
        self._results = []
        self.app = _FakeApp()


# ── config resolution (the back-compat rule) ─────────────────────────
def test_absent_transport_key_resolves_to_serial(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "config", _cfg(tmp_path))     # empty config, no [device]
    s = _FakeConn()
    s._load_from_config()
    assert s.transport == "serial"        # NOT tcp — a fresh/old install keeps serial
    assert s.refresh_hz == 50             # serial's default poll rate


def test_tcp_config_is_honored(tmp_path, monkeypatch):
    c = _cfg(tmp_path)
    c.add_section("device")
    c.set("device", "transport", "tcp")
    c.set("device", "host", "10.0.0.9")
    monkeypatch.setattr(cs, "config", c)
    s = _FakeConn()
    s._load_from_config()
    assert s.transport == "tcp" and s.host == "10.0.0.9"
    assert s.refresh_hz == 100            # tcp's default poll rate


# ── live apply ───────────────────────────────────────────────────────
def test_apply_reconfigures_board_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "config", _cfg(tmp_path))
    s = _FakeConn()
    s.transport, s.host, s.tcp_port, s.refresh_hz = "tcp", "192.168.1.5", 5555, 100
    s.apply()
    assert s.app.board.reconfigured["transport"] == "tcp"
    assert s.app.board.reconfigured["host"] == "192.168.1.5"
    assert s.app.board.poll_period == 1.0 / 100
    # persisted back to config
    assert cs.config.getdefault("device", "transport", "") == "tcp"
    assert cs.config.getdefault("device", "host", "") == "192.168.1.5"


def test_apply_tcp_without_host_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "config", _cfg(tmp_path))
    s = _FakeConn()
    s.transport, s.host = "tcp", ""
    s.apply()
    assert "no board ip" in s.status_text.lower()      # doesn't silently connect to nothing


# ── discovery result selection ───────────────────────────────────────
def test_on_device_selected_switches_to_tcp():
    s = _FakeConn()
    s._results = [{"host": "10.0.0.7", "port": 5555, "version": "v1.5.0-test"}]
    s.on_device_selected("10.0.0.7  (v1.5.0-test)")
    assert s.transport == "tcp" and s.host == "10.0.0.7" and s.tcp_port == 5555
