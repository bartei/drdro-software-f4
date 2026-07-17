"""ElsBar.set_custom_feed applies an arbitrary feed's ratio to the spindle axis.

Drives the real ElsBar.set_custom_feed on a duck-typed self (the widget's __init__ needs a
live app), using feeds.custom_feed to build the config.
"""
from dro import feeds
from dro.components.home.elsbar import ElsBar


class _Axis:
    def __init__(self):
        self.syncRatioNum = None
        self.syncRatioDen = None


class _Board:
    def __init__(self, axis):
        self._axis = axis

    def get_spindle_axis(self):
        return self._axis


class _App:
    def __init__(self, axis):
        self.board = _Board(axis)


class _FakeElsBar:
    def __init__(self, axis, index=0):
        self.app = _App(axis)
        self.mode_name = ":("
        self.current_feeds_table = []
        self.current_feeds_index = index
        self.feed_name = ":("


def test_custom_feed_ratio_pushed_to_spindle():
    axis = _Axis()
    bar = _FakeElsBar(axis)
    feed = feeds.custom_feed("Thread MM", 1.3)     # ratio 13/10

    ElsBar.set_custom_feed(bar, "Thread MM", feed)

    assert axis.syncRatioNum == 13
    assert axis.syncRatioDen == 10
    assert bar.feed_name == "1.3"
    assert bar.mode_name == "Thread MM"
    assert bar.current_feeds_table is feeds.table["Thread MM"]


def test_index_clamped_into_range_for_selected_table():
    axis = _Axis()
    # Start with an index past the end of the target table (e.g. left over from a longer tab).
    bar = _FakeElsBar(axis, index=999)
    feed = feeds.custom_feed("Feed MM", 0.05)

    ElsBar.set_custom_feed(bar, "Feed MM", feed)

    assert bar.current_feeds_index == len(feeds.table["Feed MM"]) - 1


def test_no_spindle_is_safe():
    bar = _FakeElsBar(axis=None)
    bar.app.board = _Board(None)
    feed = feeds.custom_feed("Thread IN", 16)

    ElsBar.set_custom_feed(bar, "Thread IN", feed)   # must not raise

    assert bar.feed_name == "16"