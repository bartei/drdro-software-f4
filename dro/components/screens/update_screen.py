import asyncio
import importlib.metadata
import os
import ssl
import subprocess

import aiohttp
import certifi
from kivy.clock import Clock
from kivy.logger import Logger
from kivy.properties import ListProperty, StringProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen

from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)

DEV_RELEASE = "dev (experimental)"

# This application's own repository — SOFTWARE updates. (Firmware OTA is separate:
# dro/comms/updater.py points at the drdro-firmware-f4 repo.)
GITHUB_REPO = "bartei/drdro-software-f4"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
# Git checkout + venv baked into the drdro-arch appliance image (see drdro-arch/build.sh
# and overlay/opt/drdro/app-run.sh — the app runs as root from this folder).
PROJECT_FOLDER = "/opt/drdro/app"
VENV_PIP = f"{PROJECT_FOLDER}/.venv/bin/pip"

# Verify TLS against certifi's CA bundle — same rationale as dro/comms/updater.py
# (system CA store is unreliable on some hosts).
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


class UpdateScreen(Screen):
    releases = ListProperty([])
    selected_release = StringProperty("")
    current_release = StringProperty("v" + importlib.metadata.version("drdro-software"))
    enable_update_button = BooleanProperty(False)
    allow_experimental = BooleanProperty(False)
    status = StringProperty("")

    def __init__(self, **kv):
        super().__init__(**kv)
        self._official: list[str] = []
        self._prereleases: list[str] = []
        self.schedule_refresh_releases()
        self.status = ""

    def schedule_refresh_releases(self):
        log.info("User wants to install a different release!")
        Clock.schedule_once(lambda dt: asyncio.ensure_future(self.refresh_releases(dt)))

    async def refresh_releases(self, dt):
        self.update_status("Retrieve all the releases from Github")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RELEASES_URL, ssl=_SSL_CTX) as response:
                    if response.status != 200:
                        text = await response.text()
                        log.error(f"Failed to fetch releases: {response.status} - {text}")
                        return

                    releases = await response.json()

            # Stable releases and beta prereleases (filter first, then limit)
            self._official = [item['tag_name'] for item in releases if not item['prerelease']][:10]
            self._prereleases = [item['tag_name'] for item in releases if item['prerelease']][:5]
            self._set_releases()
            self.selected_release = self.releases[0] if self.releases else ""
        except Exception as e:
            self.update_status(str(e))

    def _set_releases(self):
        """Rebuild the dropdown: stable releases, plus betas + the dev branch when experimental."""
        if self.allow_experimental:
            self.releases = self._official + self._prereleases + [DEV_RELEASE]
        else:
            self.releases = self._official

    def on_selected_release(self, instance, value):
        log.info(f"Selected release: {self.selected_release}")
        if value != "" and value != self.current_release:
            self.enable_update_button = True
        else:
            self.enable_update_button = False

    def update_status(self, status: str):
        self.status = self.status + status + "\n"

    def on_allow_experimental(self, instance, value):
        self._set_releases()
        # A now-hidden selection (beta or dev entry) falls back to the newest stable.
        if not value and self.selected_release not in self.releases:
            self.selected_release = self.releases[0] if self.releases else ""

    def install_release(self):
        log.info("User wants to install a different release!")
        if self.selected_release == DEV_RELEASE:
            self._confirm_dev_install()
        else:
            self._do_install()

    def _confirm_dev_install(self):
        content = BoxLayout(orientation="vertical", spacing=10, padding=10)

        content.add_widget(Label(
            text=(
                "Warning: You are about to install an experimental version.\n\n"
                "- Development version may be unstable or incomplete\n"
                "- Features may not work as expected\n"
                "- Data or settings could be corrupted\n"
                "- You may need to reinstall a stable version to recover"
            ),
            halign="left",
            valign="top",
            text_size=(None, None),
        ))

        buttons = BoxLayout(orientation="horizontal", spacing=10, size_hint_y=None, height=60)
        btn_cancel = Button(text="Cancel", font_size=22)
        btn_confirm = Button(text="Install Anyway", font_size=22)
        buttons.add_widget(btn_cancel)
        buttons.add_widget(btn_confirm)
        content.add_widget(buttons)

        popup = Popup(
            title="Warning: Experimental Version",
            content=content,
            size_hint=(0.7, 0.5),
            auto_dismiss=False,
        )

        btn_cancel.bind(on_release=popup.dismiss)
        btn_confirm.bind(on_release=lambda _: (popup.dismiss(), self._do_install()))

        popup.open()

    def _do_install(self):
        Clock.schedule_once(lambda dt: asyncio.ensure_future(self.perform_install(dt)))

    async def perform_install(self, dt):
        self.update_status(f"Performing installation of a new release: {self.current_release} -> {self.selected_release}")

        if not os.path.isdir(PROJECT_FOLDER):
            self.update_status(f"Project folder not found at the expected location: {PROJECT_FOLDER}")
            return

        self.update_status(f"Found project folder at: {PROJECT_FOLDER}")
        os.chdir(PROJECT_FOLDER)

        # Install with the app's own venv pip (app-run.sh activates it, but be explicit).
        pip = VENV_PIP if os.path.exists(VENV_PIP) else "pip"
        if self.selected_release == DEV_RELEASE:
            commands = [
                "git remote set-branches origin '*'",
                "git fetch --all",
                "git checkout dev",
                "git pull origin dev",
                f"{pip} install .",
                "reboot",
            ]
        else:
            commands = [
                "git fetch --all --tags",
                f"git checkout tags/{self.selected_release}",
                f"{pip} install .",
                "reboot",
            ]

        for c in commands:
            self.update_status(f"run: {c}")
            p = subprocess.Popen(
                c,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            while p.poll() is None:
                await asyncio.sleep(1)

            output = p.stdout.read().decode()
            log.info(output)
            self.update_status(f"return code: {p.returncode}")
            self.update_status(f"output: {output}")

            if p.stderr is not None:
                error = p.stderr.read().decode()
                log.error(output)
                self.update_status(f"err: {error}")

            if p.returncode != 0:
                return
