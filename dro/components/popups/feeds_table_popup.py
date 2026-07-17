from kivy.logger import Logger
from kivy.properties import ObjectProperty, StringProperty
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem

from dro import feeds

log = Logger.getChild(__name__)


class FeedButton(Button):
    text_halign = "center"
    font_style = "bold"
    font_name = StringProperty("fonts/Manrope-Bold.ttf")
    halign = "center"
    background_color = [1, 1, 1, 1]
    return_value = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def on_height(self, instance, value):
        self.font_size = value / 3


class FeedsTablePopup(Popup):
    def __init__(self, **kwargs):
        from dro.app import MainApp
        self.app: MainApp = MainApp.get_running_app()
        super().__init__(**kwargs)
        self.title = f"Select Feed"
        self.title_size = "20sp"
        self.size_hint = (0.8, 0.8)
        self.auto_dismiss = False

        panel = TabbedPanel(
            do_default_tab=False,
            tab_width=150,
        )

        for name, table in feeds.table.items():
            layout = GridLayout(cols=5)
            for idx, pitch in enumerate(table):
                layout.add_widget(
                    FeedButton(text=pitch.name, return_value=(name, idx), on_release=self.confirm)
                )
            tab = TabbedPanelItem(text=name)
            tab.add_widget(layout)
            panel.add_widget(tab)

        self.panel = panel

        # Panel + a "Custom…" button that enters an arbitrary value for the active tab
        # (pitch in mm / TPI / feed per rev, depending on the tab's unit).
        container = BoxLayout(orientation="vertical")
        container.add_widget(panel)
        container.add_widget(FeedButton(
            text="Custom…",
            size_hint_y=None,
            height=64,
            background_color=[0.3, 0.6, 1, 1],
            on_release=lambda *a: self.enter_custom(),
        ))
        self.add_widget(container)

        self.callback_fn = None
        self.custom_fn = None
        self.current_value = None

    def on_touch_down(self, touch):
        self.app.beep()
        return super().on_touch_down(touch)

    def show_with_callback(self, callback_fn, current_value=None, custom_fn=None):
        if current_value is not None:
            # Use the specified current value if passed
            self.current_value = float(current_value)

        self.callback_fn = callback_fn
        self.custom_fn = custom_fn
        self.open()

    def confirm(self, instance: FeedButton):
        try:
            value = instance.return_value
            self.callback_fn(table_name=value[0], index=value[1])
            self.dismiss()
        except Exception as e:
            log.error(str(e))
            return

    def enter_custom(self, *args):
        """Open the keypad to enter an arbitrary feed for the active tab, in its unit."""
        table_name = self.panel.current_tab.text
        self.dismiss()
        from dro.components.popups.keypad import Keypad
        Keypad().show_with_callback(
            lambda value: self._confirm_custom(table_name, value)
        )

    def _confirm_custom(self, table_name, value):
        try:
            feed = feeds.custom_feed(table_name, value)
        except ValueError as e:
            log.warning(f"Invalid custom feed: {str(e)}")
            return
        if self.custom_fn is not None:
            self.custom_fn(table_name, feed)

    def cancel(self, *args, **kwargs):
        self.dismiss()
