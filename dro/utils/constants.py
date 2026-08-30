"""Hardware-shape constants shared across the dispatcher layer."""

# Initial/default encoder-input count. The live count is board-reported: the v1.5 mainboard
# has 5 scales and announces it via the read-only `scales.count` variable, which Board reads
# on connect and applies with `_apply_scale_count()`. Stays 4 so a v1.0 board (which doesn't
# know `scales.count`) keeps exactly 4 inputs — no phantom 5th axis.
SCALES_COUNT = 4
SERVOS_COUNT = 3
