"""Machine Profiles screen — save the current machine configuration as a named
profile, apply a stored profile (auto-backup + app restart), or delete one.
See dro/profiles.py for what a profile contains.
"""
import asyncio

from kivy.clock import mainthread
from kivy.logger import Logger
from kivy.properties import BooleanProperty, ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput

from dro.profiles import ProfileManager, restart_app
from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)


class ProfileRow(BoxLayout):
    screen = ObjectProperty(rebind=True)
    entry = ObjectProperty()
    name = StringProperty("")
    detail = StringProperty("")
    kind = StringProperty("user")


class ProfilesScreen(Screen):
    busy = BooleanProperty(False)
    status_text = StringProperty("")

    def __init__(self, **kv):
        from dro.app import MainApp
        self.app: MainApp = MainApp.get_running_app()
        super().__init__(**kv)
        self.profiles = ProfileManager(self.app.board)

    @mainthread
    def _status(self, msg: str):
        log.info("profiles: %s", msg)
        self.status_text = msg

    def _spawn(self, coro):
        try:
            asyncio.get_event_loop().create_task(coro)
        except RuntimeError:
            log.error("no running asyncio loop for profiles task")
            coro.close()

    # ── lifecycle ────────────────────────────────────────────────────
    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self):
        grid = self.ids.profiles_grid
        grid.clear_widgets()
        entries = self.profiles.list_profiles()
        for entry in entries:
            detail = entry["created"]
            versions = " / ".join(
                v for v in (entry["software_version"], entry["firmware_version"]) if v
            )
            if versions:
                detail += f"  ({versions})"
            grid.add_widget(ProfileRow(
                screen=self, entry=entry, name=entry["name"],
                detail=detail, kind=entry["kind"],
            ))
        if not entries:
            self._status("No profiles yet — save the current configuration to create one")

    # ── save as new profile ──────────────────────────────────────────
    def prompt_save(self):
        content = BoxLayout(orientation="vertical", spacing=10, padding=10)
        text_input = TextInput(hint_text="Profile name", multiline=False, font_size=22,
                               size_hint_y=None, height=48)
        btn_save = Button(text="Save", font_size=22)
        btn_cancel = Button(text="Cancel", font_size=22)
        content.add_widget(text_input)
        content.add_widget(btn_save)
        content.add_widget(btn_cancel)
        popup = Popup(title="Save current configuration as…", content=content,
                      size_hint=(0.6, 0.5), auto_dismiss=False)
        btn_cancel.bind(on_release=popup.dismiss)
        btn_save.bind(on_release=lambda _: self._save(popup, text_input.text))
        popup.open()

    def _save(self, popup, name: str):
        popup.dismiss()
        name = name.strip()
        if not name:
            self._status("Profile name cannot be empty")
            return
        self._spawn(self._do_save(name))

    async def _do_save(self, name: str):
        self.busy = True
        try:
            if not self.app.board.connected:
                self._status("Board offline — profile saved without board settings")
            path = await self.profiles.save_profile(name)
            self._status(f"Saved profile '{name}' ({path.name})")
        except Exception as e:  # noqa: BLE001 — surface any failure to the UI
            log.exception("profile save failed")
            self._status(f"Save FAILED: {e}")
        finally:
            self.busy = False
            self.refresh()

    # ── apply ────────────────────────────────────────────────────────
    def confirm_apply(self, entry: dict):
        if self.busy:
            return
        content = BoxLayout(orientation="vertical", spacing=10, padding=10)
        content.add_widget(Label(
            text=f"Apply profile '{entry['name']}'?\n\nThe current configuration is backed up\n"
                 "automatically and the application restarts.",
            font_size=20, halign="center"))
        btn_apply = Button(text="Apply and Restart", font_size=22)
        btn_cancel = Button(text="Cancel", font_size=22)
        content.add_widget(btn_apply)
        content.add_widget(btn_cancel)
        popup = Popup(title="Apply profile?", content=content,
                      size_hint=(0.6, 0.6), auto_dismiss=False)
        btn_cancel.bind(on_release=popup.dismiss)
        btn_apply.bind(on_release=lambda _: (popup.dismiss(), self._spawn(self._apply(entry))))
        popup.open()

    async def _apply(self, entry: dict):
        self.busy = True
        try:
            if not self.app.board.connected:
                self._status("Board offline — applying host settings only")
            await self.profiles.apply_profile(entry["path"])
            self._status(f"Profile '{entry['name']}' applied — restarting…")
            await asyncio.sleep(0.5)  # let the status render
            restart_app()
        except Exception as e:  # noqa: BLE001 — surface any failure to the UI
            log.exception("profile apply failed")
            self._status(f"Apply FAILED: {e}")
            self.busy = False

    # ── delete ───────────────────────────────────────────────────────
    def confirm_delete(self, entry: dict):
        content = BoxLayout(orientation="vertical", spacing=10, padding=10)
        btn_delete = Button(text="Delete", font_size=22)
        btn_cancel = Button(text="Cancel", font_size=22)
        content.add_widget(btn_delete)
        content.add_widget(btn_cancel)
        popup = Popup(title=f"Delete profile '{entry['name']}'?", content=content,
                      size_hint=(0.6, 0.4), auto_dismiss=False)
        btn_cancel.bind(on_release=popup.dismiss)
        btn_delete.bind(on_release=lambda _: self._delete(popup, entry))
        popup.open()

    def _delete(self, popup, entry: dict):
        popup.dismiss()
        try:
            self.profiles.delete_profile(entry["path"])
            self._status(f"Deleted profile '{entry['name']}'")
        except OSError as e:
            self._status(f"Delete FAILED: {e}")
        self.refresh()
