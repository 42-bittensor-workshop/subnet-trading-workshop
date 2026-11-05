# The data

| File | Content |
|---|---|
| `history_15min.csv.gz` | Every subnet's pool, every 15 minutes, 2026-02-01 to 2026-03-01: 2,680 snapshots of 128 subnets |
| `holders_daily.csv.gz` | Each subnet's number of holders, once a day |

`load()` turns them into one table per field: one row per time, one column per subnet
(its `netuid`).

## Fields

| Field | Meaning |
|---|---|
| `price` | Price of one unit of the subnet's token (alpha), in TAO: about `tao_in / alpha_in` |
| `tao_in` | TAO in the subnet's pool. The 50 largest pools make the universe. |
| `alpha_in` | Alpha in the pool |
| `alpha_out` | Alpha outside the pool, held or staked |
| `holders` | Number of holders on the previous day. A day's count is known from the next day on. |
| `life` | Changes when a subnet number is given to a new subnet. Price changes across two lives are never used. |

## Sources and cleaning

- **Pool snapshots:** the chain's state at one block every 15 minutes (every 75
  blocks), fetched from TaoStats.
- **Holder counts:** from TaoSwap.
- These data come from third parties and are not covered by the repository's MIT
  license.
- **Cleaning,** by `scripts/build_data.py`:
  - root (netuid 0) is dropped;
  - amounts are converted from rao to TAO or alpha;
  - a subnet number given to a new subnet starts a new `life`, detected when the alpha
    outside the pool falls by more than half between two snapshots (8 times in
    February);
  - nothing is filled in.

During the event, the live data comes from Kusanagi (TaoSwap), in the same format and
with the same definitions.
