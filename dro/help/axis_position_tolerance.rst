In-Position Tolerance
=====================

The acceptable position error for this axis. When the remaining
distance to go is within this window, the positioning aid under the
axis readout switches to the accept color: the axis is "in position."

Units follow the display: with the DRO in MM the tolerance is edited
in millimeters, in IN mode it is edited in inches. Switching units
converts the displayed value — the physical window stays the same.

Typical Values
--------------

=================  =========
Application        Tolerance
=================  =========
General machining  0.01 mm
Precision work     0.005 mm
Rough positioning  0.1 mm
=================  =========

Notes
-----

- Configured per axis; each axis keeps its own window
- Not shown for spindle-mode axes (no linear in-position window)
- Too tight a tolerance may never show "in position" due to
  encoder noise; too loose loses the benefit of the aid
