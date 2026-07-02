"""
Machine profiles — named snapshots of the full machine configuration, so one
device can move between machines by just selecting a profile.

A profile is a single YAML file under ``~/.config/drdro-software/profiles/``
holding:

- ``metadata``: profile name, creation datetime, software + firmware versions
  (for future reference / troubleshooting), kind (``user`` or automatic
  ``backup``) and an optional note.
- ``board``: the firmware-flash-persisted variables (``BOARD_PERSISTED_VARS``,
  mirroring ``settings_t`` in the firmware's shared/Settings.h).
- ``host``: the machine-specific per-dispatcher YAML files (axes, inputs,
  servo, ELS). Display formats and network config stay device-local.

Applying a profile first auto-saves the current configuration as a timestamped
backup profile (manual rollback = apply the backup), then replaces the host
YAML files and pushes the board section to the firmware (``set`` + ``save``).
The caller restarts the app afterwards so every dispatcher rebinds cleanly.
"""

import datetime
import importlib.metadata
import os
import re
import sys

import yaml
from kivy.logger import Logger

from dro.dispatchers.saving_dispatcher import SETTINGS_FOLDER

log = Logger.getChild(__name__)

PROFILES_FOLDER = SETTINGS_FOLDER / "profiles"

# Firmware-flash-persisted variables (the settings_t payload; see the firmware's
# shared/Settings.h and docs/protocol_design.md §A.4). Live/positional variables
# (scales.pos, servo.tgt, …) deliberately excluded.
BOARD_PERSISTED_VARS = [
    "scales.num",
    "scales.den",
    "scales.sync",
    "scales.filt",
    "servo.max",
    "servo.acc",
    "servo.jog",
    "servo.idx",
    "servo.mode",
]

# Host-side YAML files that describe the machine (not the device/UI).
HOST_FILE_PATTERNS = ("Axis-*.yaml", "CoordBar-*.yaml", "ServoBar-*.yaml", "Els-*.yaml")


def _parse_value(raw: str):
    """Board values arrive as strings — store numbers in the YAML for readability."""
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "profile"


def restart_app() -> None:
    """Replace the process with a fresh instance of the application."""
    log.info("Restarting application")
    os.execv(sys.executable, [sys.executable, "-m", "dro.main"])


class ProfileManager:
    def __init__(self, board, folder=PROFILES_FOLDER):
        self.board = board
        self.folder = folder

    # ── listing ──────────────────────────────────────────────────────
    def list_profiles(self) -> list[dict]:
        """All profiles, newest first: [{path, name, created, kind, ...}, …]."""
        out = []
        if not self.folder.exists():
            return out
        for path in sorted(self.folder.glob("*.yaml")):
            try:
                with open(path, "r") as f:
                    data = yaml.safe_load(f.read()) or {}
            except (OSError, yaml.YAMLError) as e:
                log.error(f"Unreadable profile {path}: {str(e)}")
                continue
            meta = data.get("metadata", {})
            out.append({
                "path": path,
                "name": meta.get("name", path.stem),
                "created": meta.get("created", ""),
                "kind": meta.get("kind", "user"),
                "software_version": meta.get("software_version", ""),
                "firmware_version": meta.get("firmware_version", ""),
                "note": meta.get("note", ""),
            })
        out.sort(key=lambda p: p["created"], reverse=True)
        return out

    # ── snapshots ────────────────────────────────────────────────────
    async def snapshot_board(self) -> dict:
        """Fresh dump of the board-persisted variables ({} when disconnected)."""
        if not self.board.connected:
            log.warning("Board disconnected — profile will carry no board settings")
            return {}
        r = await self.board.connection.settings()
        if not r.crc_ok:
            log.warning("Board settings dump failed — profile will carry no board settings")
            return {}
        snap = {}
        for name in BOARD_PERSISTED_VARS:
            raw = r.values.get(name)
            if raw is None:
                continue  # older firmware without this variable
            parts = [_parse_value(p) for p in raw.split(",")]
            snap[name] = parts if len(parts) > 1 else parts[0]
        return snap

    def _host_files(self) -> dict:
        """Contents of the machine-specific YAML files, keyed by file stem."""
        host = {}
        for pattern in HOST_FILE_PATTERNS:
            for path in sorted(SETTINGS_FOLDER.glob(pattern)):
                try:
                    with open(path, "r") as f:
                        host[path.stem] = yaml.safe_load(f.read()) or {}
                except (OSError, yaml.YAMLError) as e:
                    log.error(f"Unreadable settings file {path}: {str(e)}")
        return host

    # ── save / apply / delete ────────────────────────────────────────
    async def save_profile(self, name: str, kind: str = "user", note: str = ""):
        """Snapshot the current configuration into a new profile file."""
        os.makedirs(self.folder, exist_ok=True)
        data = {
            "metadata": {
                "name": name,
                "created": datetime.datetime.now().isoformat(timespec="seconds"),
                "software_version": "v" + importlib.metadata.version("drdro-software"),
                "firmware_version": getattr(self.board, "firmware_version", "") or "unknown",
                "kind": kind,
            },
            "board": await self.snapshot_board(),
            "host": self._host_files(),
        }
        if note:
            data["metadata"]["note"] = note
        path = self.folder / f"{_safe_name(name)}.yaml"
        with open(path, "w") as f:
            yaml.dump(data, f, sort_keys=False)
        log.info(f"Saved profile {path}")
        return path

    async def backup_current(self, note: str = ""):
        """Timestamped automatic backup of the current configuration."""
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        return await self.save_profile(f"backup-{stamp}", kind="backup", note=note)

    async def apply_profile(self, path, backup: bool = True) -> dict:
        """Replace the current configuration with the profile's.

        Auto-backs-up first, rewrites the host YAML files, pushes + saves the
        board section. The caller must restart the app (restart_app()) so the
        dispatchers pick the new files up.
        """
        with open(path, "r") as f:
            data = yaml.safe_load(f.read()) or {}
        meta = data.get("metadata", {})

        if backup:
            await self.backup_current(note=f"automatic backup before applying '{meta.get('name', path)}'")

        # Host files: remove the current machine set (axis count may differ),
        # then write the profile's.
        for pattern in HOST_FILE_PATTERNS:
            for old in SETTINGS_FOLDER.glob(pattern):
                old.unlink()
        for stem, content in (data.get("host") or {}).items():
            with open(SETTINGS_FOLDER / f"{stem}.yaml", "w") as f:
                yaml.dump(content, f)

        await self.push_board_settings(data.get("board") or {})
        log.info(f"Applied profile {path}")
        return meta

    async def push_board_settings(self, board_section: dict) -> bool:
        """Write a profile's board section to the firmware and persist it."""
        if not board_section:
            return True
        if not self.board.connected:
            log.warning("Board disconnected — board settings not pushed")
            return False
        conn = self.board.connection
        for name, value in board_section.items():
            if name not in BOARD_PERSISTED_VARS:
                log.warning(f"Skipping unknown board variable '{name}'")
                continue
            if isinstance(value, list):
                for idx, v in enumerate(value):
                    await conn.set(name, v, idx)
            else:
                await conn.set(name, value)
        r = await conn.save()
        return bool(r)

    async def restore_board_settings(self, board_section: dict) -> int:
        """Push back any board values that differ from `board_section` (a prior
        snapshot). Returns how many variables were restored; saves only when
        something actually changed (spares the flash)."""
        if not board_section:
            return 0
        current = await self.snapshot_board()
        changed = {k: v for k, v in board_section.items() if current.get(k) != v}
        if not changed:
            return 0
        log.warning(f"Board settings lost after update — restoring {sorted(changed)}")
        await self.push_board_settings(changed)
        return len(changed)

    def delete_profile(self, path) -> None:
        os.remove(path)
        log.info(f"Deleted profile {path}")
