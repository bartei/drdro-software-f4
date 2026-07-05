# NixOS dev shell for running the Kivy UI locally.
#
# Kivy's manylinux wheels dlopen system libraries by soname (libGL.so.1, libmtdev.so.1),
# but nothing puts them on LD_LIBRARY_PATH on NixOS, so the SDL2/GL window provider fails
# to initialise and the app crashes (Window is None). This shell exports LD_LIBRARY_PATH so
# `uv run python -m dro.main` finds them. libglvnd supplies the libGL.so.1 GLX dispatcher,
# which then loads the mesa vendor (libGLX_mesa) + DRI driver from /run/opengl-driver/lib.
#
# Usage:
#   nix-shell --run 'uv run python -m dro.main'
# or:
#   nix-shell
#   uv run python -m dro.main
{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  packages = [ pkgs.uv ];

  shellHook = ''
    export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [
      pkgs.libglvnd          # libGL.so.1 — GLX dispatcher (loads the mesa vendor below)
      pkgs.mtdev             # libmtdev.so.1 — multitouch input provider
      pkgs.stdenv.cc.cc.lib  # libstdc++ — native deps (e.g. greenlet)
      pkgs.alsa-lib          # libasound.so.2 — SDL audio (ALSA routes to pipewire via
                             # /etc/alsa/conf.d; matches the Pi image, which is ALSA-only)
    ]}:/run/opengl-driver/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    # The Kivy wheel's bundled SDL2 deadlocks on its pulseaudio driver inside windowed apps
    # (main thread parks on a futex against the PulseMainloop thread; no pipewire driver is
    # compiled into the wheel). ALSA→pipewire works — pin it.
    export SDL_AUDIODRIVER=alsa
  '';
}
