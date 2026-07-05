Approach Beeper
===============

An audible companion to the positioning aid. Once an axis has a
destination (nominal) set, the beeper sounds as you traverse toward
it: the beeps get **faster and higher-pitched** the closer you get.

On arrival — within the axis' in-position tolerance — a solid tone
sounds for about a second and then goes silent, so it confirms the
position without nagging while you work. It sounds again only if the
axis leaves and re-enters the tolerance window.

Notes
-----

- Uses the same volume as every other sound (Sound Volume; 0 mutes)
- Only active for axes with a destination set; spindle axes are
  excluded
- The tone is synthesized, so there is no audio file to manage
- Turn this off to keep the graphic aid without the sound
