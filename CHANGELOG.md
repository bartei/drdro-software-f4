# CHANGELOG

<!-- version list -->

## v1.6.0 (2026-07-05)

### Bug Fixes

- Positioning aid scale is now unit-independent
  ([`ab39232`](https://github.com/bartei/drdro-software-f4/commit/ab39232f615e343be16c282253cf879ba0ced978))

### Features

- Synthesized approach beeper (PT 855 G2 audible cue)
  ([`41d2e6b`](https://github.com/bartei/drdro-software-f4/commit/41d2e6b84c7c123d4412befcce8b689040334261))


## v1.5.0 (2026-07-05)

### Bug Fixes

- Make beep() actually play — audio was a stub since the port
  ([`b0dd210`](https://github.com/bartei/drdro-software-f4/commit/b0dd21050ac32b1413c793c03c5fea90138ec320))

- Rename PositioningAid on_target_color property — the on_ prefix is Kivy handler syntax
  ([`b3b95ed`](https://github.com/bartei/drdro-software-f4/commit/b3b95edfc26c96cd76711a8ab885af56c498fe8c))

### Features

- Finalize the distance-to-go positioning aid (PT 855 G1/G2)
  ([`ef6610e`](https://github.com/bartei/drdro-software-f4/commit/ef6610e7b1d5e104bf84c18615b15ad175c23a82))

- Per-axis in-position tolerance for the positioning aid
  ([`af779f8`](https://github.com/bartei/drdro-software-f4/commit/af779f8afe6e2382218492969b5d9bf51426fe1a))


## v1.5.0-beta.1 (2026-07-03)

### Chores

- Move documentation website to its own repo
  ([`dc9ef38`](https://github.com/bartei/drdro-software-f4/commit/dc9ef38eab141dc766af1ef43ff71c151523f1bd))

### Continuous Integration

- Add mock static content deploy pipeline
  ([`74597e2`](https://github.com/bartei/drdro-software-f4/commit/74597e2c4e4899b4fa04b566e3e3553722081851))

- Remove static content deploy pipeline
  ([`1bf39c8`](https://github.com/bartei/drdro-software-f4/commit/1bf39c8bd6ab2680d3932f9ae8823542c6948279))

### Documentation

- **website**: Add documentation site and wire static deploy
  ([`ceacb6a`](https://github.com/bartei/drdro-software-f4/commit/ceacb6ab5a3b7be03b504abe20c3a518c30ec744))

- **website**: Add Videos page with creator + community demos
  ([`2521e64`](https://github.com/bartei/drdro-software-f4/commit/2521e64c907b5037001c95dd65fb6ca6d3637cb7))

- **website**: Use the drDRO logo for site brand and favicon
  ([`807bba5`](https://github.com/bartei/drdro-software-f4/commit/807bba5a88f8b94f139d2e1fdd5629adade988c0))

### Features

- Add distance-to-go target and graphic positioning aid to coordbars
  ([`45772ed`](https://github.com/bartei/drdro-software-f4/commit/45772eda3fb8051f3d5988cd8ba683e5bb1b0bec))


## v1.4.0 (2026-07-02)

### Bug Fixes

- **update**: Point software updates at drdro-software-f4, not RCP
  ([`5a0a83a`](https://github.com/bartei/drdro-software-f4/commit/5a0a83acdef850f05af72d0fd99ab199ae2003ac))

### Code Style

- **ui**: Soften RetroProgressBar fill, drop the frame
  ([`1c18ce6`](https://github.com/bartei/drdro-software-f4/commit/1c18ce69276756e2720d43a2ad5ec4f3eb9070cf))

### Continuous Integration

- Beta prereleases on dev; fold beta notes into stable releases
  ([`61a1d21`](https://github.com/bartei/drdro-software-f4/commit/61a1d21108cc91be97245f2fe334cd4bdd2db502))

### Documentation

- Resume + design notes for filter UI, profiles, compat banner, update-screen fix
  ([`8d136d8`](https://github.com/bartei/drdro-software-f4/commit/8d136d8fc04233c532bbc99a457e5c4e89bc3183))

### Features

- **profiles**: Machine profiles + firmware-update settings backup/restore
  ([`553d8b5`](https://github.com/bartei/drdro-software-f4/commit/553d8b5487f9b0534fe8bf8c1212a1c2e8bb38e6))

- **scales**: Encoder filter setting on the input screen (scales.filt)
  ([`c7f85c3`](https://github.com/bartei/drdro-software-f4/commit/c7f85c364ee93559b2b8f903d3ff39d6c38c6e37))

- **update**: Firmware-compat check + tap-to-update banner on home
  ([`3e2dd0a`](https://github.com/bartei/drdro-software-f4/commit/3e2dd0afbc016f9bb640043d5dd34b18264d505d))


## v1.3.0 (2026-07-01)

### Chores

- Add shell.nix for NixOS dev
  ([`663f7ef`](https://github.com/bartei/drdro-software-f4/commit/663f7efef8615c4419ad74bdbee65381552a2490))

### Features

- **servo**: Board-owned indexing feedrate; drop max-speed override
  ([`77edec9`](https://github.com/bartei/drdro-software-f4/commit/77edec92a3ac3907fc060a6a4822e2daf4a9b5fb))

- **ui**: RetroProgressBar — solid-fill, 1px-frame progress bar
  ([`0e42489`](https://github.com/bartei/drdro-software-f4/commit/0e42489cdc2fcbfdaec2f037d8e20a547768d24c))


## v1.2.0 (2026-06-30)

### Features

- **ui**: Declutter home — hide debug ribbon by default, add Stats screen
  ([`c616da7`](https://github.com/bartei/drdro-software-f4/commit/c616da724456e1196482d8fa88da18efb558bba6))


## v1.1.3 (2026-06-30)

### Bug Fixes

- **servo**: Jog no longer triggers a flash save (200 ms position stall)
  ([`3bc2cd9`](https://github.com/bartei/drdro-software-f4/commit/3bc2cd91b31922fdd8783d9bde20a3eaa466d23d))


## v1.1.2 (2026-06-30)

### Performance Improvements

- **board**: Rate-limit sta poll to target (subtract round-trip); show sta Hz
  ([`7b9fc0e`](https://github.com/bartei/drdro-software-f4/commit/7b9fc0e00c16da293a1429a8ee2eceeaaaa05a8c))


## v1.1.1 (2026-06-30)

### Bug Fixes

- Remove Sentry, fix TraceOutput leak, demote debug print (Phase 6 polish)
  ([`3fbe6e4`](https://github.com/bartei/drdro-software-f4/commit/3fbe6e4cf0c2a6999d4aa13f47e2c65e49056285))


## v1.1.0 (2026-06-30)

### Features

- **firmware**: Robust GitHub release fetch (certifi) + GPL relicense
  ([`4e1b8fc`](https://github.com/bartei/drdro-software-f4/commit/4e1b8fca3886d7aa4ac30c3479544487b25407df))


## v1.0.0 (2026-06-30)

- Initial Release
