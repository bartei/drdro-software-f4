import os

# Keep Kivy from consuming pytest's argv when the dispatcher layer is imported headless.
os.environ.setdefault("KIVY_NO_ARGS", "1")

# Some UI modules (e.g. elsbar) load KV that pulls in widgets which, in turn, import
# kivy.core.window — importing that module *creates* a Window. On a headless CI runner with
# no display that hard-crashes the interpreter. Force SDL's dummy video/audio drivers and a
# mock GL backend so any Window created during collection is off-screen and can't crash.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("KIVY_GL_BACKEND", "mock")
