"""Synthesized tones for UI beeps and the approach cue — stdlib only (no numpy / PortAudio).

Generates short sine WAVs (with a fade envelope so there's no click at the edges) into the temp
dir, caches them by (freq, ms), and plays them through Kivy's SoundLoader (SDL2) — the same
backend the app already uses, so this needs no extra dependency and no MP3. Cached tones load
once and replay instantly, which is what the approach beeper needs.
"""
import array
import math
import os
import tempfile
import wave

from kivy.core.audio import SoundLoader
from kivy.logger import Logger

log = Logger.getChild(__name__)

_RATE = 44100
_cache = {}          # (freq, ms) -> Sound
_unavailable = False  # latch once no audio provider is found, so we stop retrying


def _tone_path(freq, ms, fade_ms=6):
    path = os.path.join(tempfile.gettempdir(), f"drdro_tone_{int(freq)}_{int(ms)}.wav")
    if os.path.exists(path):
        return path
    n = int(_RATE * ms / 1000)
    fade = max(1, int(_RATE * fade_ms / 1000))
    buf = array.array("h")
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade)  # linear fade in/out
        buf.append(int(32767 * math.sin(2 * math.pi * freq * i / _RATE) * env))
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_RATE)
        w.writeframes(buf.tobytes())
    return path


def get_tone(freq, ms):
    """Return a cached Sound for (freq, ms), generating the WAV on first use. None if audio
    is unavailable (latched after the first failure so callers can fire-and-forget)."""
    global _unavailable
    if _unavailable:
        return None
    key = (int(freq), int(ms))
    sound = _cache.get(key)
    if sound is None:
        sound = SoundLoader.load(_tone_path(freq, ms))
        if sound is None:
            _unavailable = True
            log.error("tone: no audio provider available; sounds disabled")
            return None
        _cache[key] = sound
    return sound


def play_tone(freq, ms, volume=1.0):
    """Play a synthesized sine tone. Safe to call with no audio device (no-op)."""
    sound = get_tone(freq, ms)
    if sound is not None:
        sound.volume = max(0.0, min(1.0, volume))
        sound.play()
    return sound
