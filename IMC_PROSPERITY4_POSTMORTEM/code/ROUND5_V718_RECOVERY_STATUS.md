# Round 5 v7.18 Recovery Status

## Result

The original `trader_r5_v7_18_submit.py` file was corrupted and could not be recovered byte-for-byte.

I searched the available project folders, user archives, Python caches, Git's
unreachable objects, local Codex session history, and Time Machine. The source
file itself cannot be recovered. This repository therefore does **not** include a
reconstructed file presented as the original submission.

## What Was Recovered

The April 30, 2026 local Codex session records the exact final-file lineage:

```text
trader_r5_v7_16_tailguard_submit.py
  -> trader_r5_v7_17_sq0_research.py
  -> trader_r5_v7_18_submit.py
```

The only trading-logic change from `v7_16` to `v7_18` was:

```python
SQ_BASE_CAP = 0
```

This applied only when the first-tick condition
`MICROCHIP_SQUARE - MICROCHIP_OVAL > 6000` identified a day-four-like regime.
In that case, the strategy set the `MICROCHIP_SQUARE` directional cap to zero
and disabled the `MICROCHIP_RECTANGLE x TRANSLATOR_ASTRO_BLACK` pair module.
It kept `SLEEP_POD_SUEDE` active. The competing v7.17 version also disabled
SUEDE; v7.18 deliberately did not.

## Recorded Validation

The archived session recorded the following strict event-backtest result for
v7.18:

| Metric | Recorded result |
| --- | ---: |
| Total PnL | +636,557 |
| Day 2 | +224,280 |
| Day 3 | +231,353 |
| Day 4 | +180,924 |
| Maximum drawdown | 306,560 |
| Order-limit rejections | 0 |

It also recorded two live-log replays with zero order-limit rejections. In the
second replay, the day-four-like condition held; `MICROCHIP_SQUARE` had zero
submission fills, `SLEEP_POD_SUEDE` remained active, and the pair module stayed
disabled.

## Why There Is No Replacement Script Here

The session archive contains the beginning of the script and the exact patches,
but not the full final body. Recreating a script from those fragments could make
a runnable approximation, but it would not be the original submission and could
silently change execution behavior. For a portfolio record, the more honest
choice is to preserve the verified design and validation record instead.

The original file can still be added here later if it is found in a local
submission export, editor history, or another machine.
