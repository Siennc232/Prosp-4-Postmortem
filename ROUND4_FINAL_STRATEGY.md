# Round 4: Full-Day Inventory and Settlement Risk

## Final Strategy

The final Round 4 strategy kept `HYDROGEL_PACK` as a conservative fair-value product. It used `VELVETFRUIT_EXTRACT` as the main inventory engine. It used selected VELVET vouchers for premium capture and inventory cycling. I chose the balanced version rather than the highest-PnL version because its late voucher exposure was less concentrated.

## 1. Data and Market Interpretation

Round 4 added trader identifiers and another day of data. I tested whether trader behavior was stable across days. It was not stable enough to justify direct copy trading. Trader identifiers were useful for explaining activity, but not as a standalone source of alpha.

I then replayed complete days. This changed the analysis. Early-session results did not predict later performance. VELVET could drift for long periods. Voucher positions could look weak during the day and recover near settlement.

`HYDROGEL_PACK` remained relatively independent from the VELVET and voucher risks. VELVET remained more active but more regime-sensitive. The more useful vouchers were near-the-money and moderately out-of-the-money strikes with observable premium flow. Deep in-the-money and floor-priced vouchers were less reliable.

## 2. Strategy Choice

I continued to use outer-book fair value for HYDROGEL. I kept its size modest and used it as a stable support strategy.

I used VELVET as the central inventory product. The entry threshold widened after the open, when the market regime became clearer. This reduced unnecessary early fills without abandoning the mean-reversion mechanism.

I used a small voucher ladder rather than treating all strikes equally. Voucher trades were tied to VELVET inventory and rich premium. I allowed certain positions to remain open late when the data supported settlement value. Trader identifiers only acted as minor context filters.

## 3. Backtest Findings and Revisions

The most important backtest result was that early profit could not be extrapolated to the full day. I stopped using short time slices as a performance proxy.

I also tested forced end-of-day flattening and generic trailing exits. They reduced visible drawdown, but they often removed the later reversion or settlement payoff. I rejected them as broad rules.

I compared candidates by full-day PnL, per-day results, drawdown, and stress scenarios. This led me to prefer a balanced final strategy. It accepted some lower headline PnL in exchange for lower concentration in late voucher inventory.
