"""Every rule of the game, in one place. docs/RULES.md explains each one."""

START_BALANCE = 1000.0   # virtual TAO every student starts with
ROUND_MINUTES = 15       # weights are sent every 15 minutes
HALT_MINUTES = 5         # pause between the deadline and the trade
UNIVERSE_SIZE = 50       # only the 50 subnets with the most TAO in their pool
MAX_SUBNETS = 10         # at most 10 subnets per list of weights

# Set on the February 2026 history with scripts/calibrate.py (docs/RULES.md):
FACTOR = 20              # the gain over the market is multiplied by 20: a typical round moves ~1%
FEE_RATE = 0.0025        # fee: 0.25% of every amount traded; random trading loses what a simple signal gains
