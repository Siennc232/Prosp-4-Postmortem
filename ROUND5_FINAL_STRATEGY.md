# Round 5: Execution Realism and Portfolio Robustness

## Final Strategy

The final Round 5 strategy was a cap-safe portfolio of validated directional products, selective inside-spread quotes, and small family-level risk controls. Its main purpose was robustness. It did not try to trade every product or maximize one historical return number.

## 1. Data and Market Interpretation

Round 5 had a much larger product universe, with a position limit of 10 for every product. I measured daily and intraday drift, volatility, spread, trade frequency, product-level PnL, and drawdown. I also grouped related products into families.

The live logs changed the research direction. Many fills occurred when an inside quote was hit by a market trade. An early backtester only filled an order after the best quote crossed its limit price. That model did not match live execution.

The live data also disproved an overly broad correction. A model that gave fills to deep quotes was too optimistic. For example, a `MICROCHIP_CIRCLE` idea looked attractive in the early replay but did not trade in the live log. This made live fill-fit a hard requirement for new modules.

I also found that a cross-day price trend did not guarantee an intraday trend. Several products had higher daily average prices but still fell during much of the session. This created the day-four tail risk in the initial portfolio.

## 2. Strategy Choice

I selected products only after checking whether their fill mechanism, PnL, and drawdown were reasonable across days. For validated directional products, the strategy used inside-spread quotes and strict position limits.

I added one shared order-safety layer. It reserved buy and sell capacity during each tick. This prevented a base order and a family overlay from exceeding the same product limit.

I treated family relationships as risk information. The PEBBLES basket had a stable price identity, but its deviations reverted too quickly to support a large standalone mean-reversion strategy. I kept it as a small overlay. I used a targeted gate for `MICROCHIP_SQUARE` when its early relative move resembled the day-four reversal pattern. I did not use a broad rule that disabled the entire family.

## 3. Backtest Findings and Revisions

The first backtest was not reliable because its fill model was wrong. I changed it to use market trades as the fill signal for inside quotes. I then made the model stricter for deep quotes. This removed several apparent opportunities.

I also found a PEBBLES order-limit bug. The base strategy and the overlay could each use the full capacity. Live orders were rejected when both appeared in the same tick. I fixed this with per-tick order reservation and checked that the simulated reject count was zero.

Finally, I moved from total PnL to per-day PnL, drawdown, family exposure, and live-log fit. This overturned several early beliefs. Adding more products was not always useful. Symmetric market making was not a reliable default. A high backtest return was not credible without realistic fills. The final strategy used fewer modules and specific controls for diagnosed tail risks.
