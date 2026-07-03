# drDRO documentation website

A dependency-free static documentation site for **drDRO** — the Kivy touchscreen DRO / rotary
controller for the drDRO STM32 board.

## Pages

| File | Purpose |
|---|---|
| `index.html` | Landing / overview, feature highlights, Pi compatibility summary |
| `features.html` | Full screen-by-screen functionality reference (with screenshots) |
| `screenshots.html` | Gallery of every screen |
| `flash.html` | Get started: **flash wizard** (live GitHub release download), first boot, tested Raspberry Pi models |
| `develop.html` | Run & develop the app locally on Linux (incl. NixOS) |
| `reference.html` | Architecture, RS-485 line protocol, variable registry, firmware-update flow |

Assets live under `assets/` (`css/`, `js/`, `img/`, `shots/`). Screenshots in `assets/shots/`
are real captures of the app at 1024×600.

## What the "flash tool" is (and isn't)

Browsers cannot write a raw OS image to an SD card — there is no web API for raw block-device
access (this is why Raspberry Pi Imager / balenaEtcher are native apps). So `flash.html` is a
**guided wizard**: it live-fetches the latest stable image from the
[`drdro-arch`](https://github.com/bartei/drdro-arch) GitHub releases (`assets/js/flash.js`),
offers a one-click download + checksum, and walks the user through flashing with Raspberry Pi
Imager or `dd`. The GitHub fetch is client-side and needs no backend.

## Preview locally

It's plain HTML/CSS/JS — no build step. Serve the folder with any static server so the
`fetch()` calls and relative paths behave (opening via `file://` mostly works, but a server is
cleaner):

```bash
cd website
python3 -m http.server 8000
# open http://localhost:8000
```

## Deploy to GitHub Pages

A workflow at `.github/workflows/pages.yml` publishes this folder to GitHub Pages on pushes to
`main` that touch `website/**` (and on manual dispatch). Enable it once under
**Settings → Pages → Build and deployment → Source: GitHub Actions**.

To host elsewhere, just upload the contents of `website/` to any static host — there is no
server-side component.

## Updating the screenshots

Screenshots are captured by touring the app at 1024×600 and saving each screen. On the dev
machine the app can be driven headless (Xvfb + software GL) or on a real display; copy the PNGs
into `assets/shots/` using the clean names referenced by the HTML (`home-dro.png`, `setup.png`,
`firmware.png`, …).
