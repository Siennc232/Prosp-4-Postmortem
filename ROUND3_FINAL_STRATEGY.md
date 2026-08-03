# Round 3: Stable Fair Value and Selective Voucher Trading

## Final Strategy

The final Round 3 approach combined fair-value market making in `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT` with a small, selective voucher overlay. The focus was execution quality and inventory control. It was not a broad option-arbitrage strategy.

The recovered implementation is [trader_r3_v3_voucher_c3_r3base_v52c80_20260426.py](code/trader_r3_v3_voucher_c3_r3base_v52c80_20260426.py).

## 1. Data and Market Interpretation

I studied the order book, raw mid-price, wall-mid, spread, recent returns, and trade locations for each product.

`HYDROGEL_PACK` had a stable long-run level, but it was not fixed at 10,000. The best bid and ask moved frequently because of small displayed orders. The wall-mid was more stable. This suggested a mean-reversion strategy with modest inventory, not a fixed-price trade.

`VELVETFRUIT_EXTRACT` had tighter spreads and more activity. It showed mean reversion at short horizons, but also occasional directional drift. It could support a more active inventory strategy, provided the strategy did not keep adding in a losing direction.

The VELVET vouchers initially appeared to offer implied-volatility mispricing. After I compared the signal with actual spreads and trade direction, I found that many of these gaps were not executable. The useful vouchers were those with enough flow and a premium that could be sold and later covered.

## 2. Strategy Choice

For the two underlying products, I used wall-mid or outer-book fair value as the reference price. The strategy took or quoted prices only when they were meaningfully away from that reference. It skewed orders according to current inventory.

For VELVET, I added a slower fair-value anchor and an inventory clear rule. This allowed the strategy to respond to short-term movement without treating a temporary trend as permanent fair value.

For vouchers, I used a limited short-premium overlay. It was opened only in selected strikes and only when the VELVET inventory setup supported it. The position was covered when VELVET moved back toward fair value.

## 3. Backtest Findings and Revisions

The backtest showed that a theoretical option residual was not enough. Bid-ask costs and limited fills removed much of the apparent edge. I therefore reduced the number of traded strikes and stopped treating deep in-the-money vouchers as a way to bypass the VELVET position limit.

I also corrected the historical time-to-expiry mapping and used empirical voucher behavior as a check on theoretical delta. These changes made the strategy more conservative, but more credible.

One HYDROGEL-only live test finished at +1,310. It had reasonable fills, but a short inventory was still painful during a rally. This was my practical reason for keeping HYDROGEL small. A good mean-reversion signal was not enough to justify a large cap.

The main conclusion was simple: fair value matters only when the strategy can cross the spread, manage inventory, and wait for the reversion that the data supports.
