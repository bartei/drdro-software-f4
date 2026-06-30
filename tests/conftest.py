import os

# Keep Kivy from consuming pytest's argv when the dispatcher layer is imported headless.
os.environ.setdefault("KIVY_NO_ARGS", "1")
