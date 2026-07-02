Encoder Input Filter
====================

Each encoder input is read by an STM32 hardware timer with a built-in
digital glitch filter. The filter samples the input signal and only
accepts an edge after N consecutive identical samples, so electrical
noise spikes shorter than the filter time are ignored instead of being
counted as movement.

The filter value (0–15) selects how aggressive the filtering is:

- **0** disables the filter entirely — every edge is counted.
- Higher values reject longer noise pulses, but also limit the maximum
  counting frequency: a real encoder pulse shorter than the filter time
  is rejected too, causing lost counts at high speed.

The setting is stored in the controller board's flash memory, one value
per encoder input, and takes effect immediately when changed.
The default is **5**.

Filter Values
-------------

All encoder timers sample at 100 MHz. "Rejects" is the longest noise
pulse suppressed; "Max frequency" is the highest quadrature signal
frequency per channel that still passes (each signal level must persist
longer than the filter time).

======  ============  ==============
Value   Rejects       Max frequency
======  ============  ==============
0       no filter     unlimited
1       < 20 ns       25 MHz
2       < 40 ns       12.5 MHz
3       < 80 ns       6.25 MHz
4       < 120 ns      4.17 MHz
5       < 160 ns      3.12 MHz
6       < 240 ns      2.08 MHz
7       < 320 ns      1.56 MHz
8       < 480 ns      1.04 MHz
9       < 640 ns      781 kHz
10      < 800 ns      625 kHz
11      < 960 ns      521 kHz
12      < 1.28 µs     391 kHz
13      < 1.6 µs      312 kHz
14      < 1.92 µs     260 kHz
15      < 2.56 µs     195 kHz
======  ============  ==============

Choosing a Value
----------------

Work out your maximum counting frequency first:

    f_max = (counts per mm × max speed in mm/s) / 4

for linear scales, or

    f_max = (PPR × max RPM) / 60

for rotary encoders — then pick the highest filter value whose maximum
frequency is comfortably above it (a 2–4× margin is a good rule of
thumb).

Example: a 5 µm glass scale (200 counts/mm quadrature) traversing at
100 mm/s produces 20 kHz — even the strongest filter (15, 195 kHz)
passes that with a wide margin.

Tips
----

- If an axis creeps or jitters while the machine is stationary
  (electrical noise from VFDs, spindle motors, relays), increase the
  filter value.
- If readings lose counts at high traverse speed, the filter may be
  rejecting real pulses — decrease the value.
- The default of 5 (160 ns, ≈3 MHz) is far above the signal rate of
  typical glass scales and rotary encoders, so raising it towards 15 is
  usually safe on noisy machines.
