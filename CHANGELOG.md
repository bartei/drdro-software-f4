# CHANGELOG

<!-- version list -->

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
