# IMC Prosperity 4: Trading Research Notes

This was an independent trading research project. I used the IMC Prosperity 4 market simulator to study how market data, execution assumptions, and risk controls interact. My goal was not to find one perfect rule. It was to build a more reliable research process.

I focused on three questions in every round:

1. What does the market data say about each product?
2. Which strategy follows from that evidence?
3. What does the backtest prove wrong, and how should the strategy change?

The final notes for each round are here:

- [Round 3: Stable fair value and option execution](/Users/sienn/Desktop/IMC_Prosperity4/ROUND_5_analysis/IMC_PROSPERITY4_POSTMORTEM/ROUND3_FINAL_STRATEGY.md)
- [Round 4: Full-day inventory and settlement risk](/Users/sienn/Desktop/IMC_Prosperity4/ROUND_5_analysis/IMC_PROSPERITY4_POSTMORTEM/ROUND4_FINAL_STRATEGY.md)
- [Round 5: Execution realism and portfolio robustness](/Users/sienn/Desktop/IMC_Prosperity4/ROUND_5_analysis/IMC_PROSPERITY4_POSTMORTEM/ROUND5_FINAL_STRATEGY.md)

## Research Approach

I treated each product as a market microstructure problem before treating it as a prediction problem. I looked at mid prices, depth, spreads, trades around the mid, short-horizon returns, inventory paths, and profit and loss by day. For related products, I also checked whether they moved together or created the same risk under different names.

I did not assume that a signal was useful just because it looked good in a chart. A signal also had to survive the spread, the position limit, the fill model, and different trading days.

### Why I Used Wall-Mid

The best bid and best ask can move because of very small orders. This made the raw mid-price noisy in the Round 3 and Round 4 data. I therefore compared it with a `wall-mid`: the average of price levels that held meaningful displayed depth.

Wall-mid was more stable for `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT`. It helped separate a short-lived quote change from a change in the broader order book. I used it as a fair-value reference, not as a prediction that every price would revert immediately.

This was an important distinction. A stable fair-value estimate can still lose money when the strategy fills too early, holds too much inventory, or assumes an unrealistic fill rate.

## Round 3

### 1. Data and Market Interpretation

Round 3 contained `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, and call vouchers on VELVET.

`HYDROGEL_PACK` traded around a stable level, but it was not fixed at 10,000. Its spread was wide and its best quotes bounced often. The wall-mid was a better reference than the raw mid.

`VELVETFRUIT_EXTRACT` was more liquid and mean-reverted more cleanly. It also had periods of directional drift. This made it a useful trading product, but a risky one to hold at a large fixed inventory.

The vouchers looked attractive under an implied-volatility model. The trade data changed my view. Many apparent pricing gaps were smaller than the spread. Some strikes had too little trading activity. The more useful observation was that certain vouchers could be sold at rich prices and later covered when the underlying inventory cycle reversed.

### 2. Strategy Choice

I used wall-mid or outer-book fair value for the two underlying products. The strategy bought or sold only when the displayed price was sufficiently far from that reference. It also used inventory controls to avoid treating every deviation as a large directional signal.

For vouchers, I used a small and selective short-premium overlay. It was tied to the VELVET position cycle. The strategy covered the voucher position when the underlying moved back toward fair value. This was more realistic than trying to trade every theoretical volatility residual.

### 3. Backtest Findings and Revisions

The first major revision was to reject a simple option-pricing story. A theoretical residual was not enough after bid-ask costs and limited fills.

I also corrected the time-to-expiry mapping and used empirical relationships between the vouchers and VELVET instead of relying only on textbook delta. These checks made the strategy smaller and more selective. The final Round 3 approach was a stable fair-value strategy with a limited voucher overlay, not a broad volatility-arbitrage book.

## Round 4

### 1. Data and Market Interpretation

Round 4 used the same underlying products and vouchers, but it added trader identifiers and another day of data. I used the identifiers as context rather than as a direct signal. A trader who appeared informative on one day was often not predictive on another.

The more important discovery came from full-day replay. The first part of the day did not represent the rest of the session. VELVET drift, voucher inventory, and settlement value could all change later in the day.

`HYDROGEL_PACK` remained relatively independent from the VELVET and voucher book. `VELVETFRUIT_EXTRACT` remained the core inventory product. Near-the-money and moderately out-of-the-money vouchers had more usable premium flow than deep in-the-money or floor-priced strikes.

### 2. Strategy Choice

I kept HYDROGEL as a conservative wall-mid strategy. I used VELVET as the main inventory engine and widened its entry threshold after the opening period.

I used voucher positions to express rich premium and to manage the VELVET inventory cycle. I kept the strategy selective by strike. I did not treat all vouchers as interchangeable. Trader identifiers were only small filters. They did not trigger trades by themselves.

### 3. Backtest Findings and Revisions

Round 4 overturned two intuitive ideas. First, early-session profit did not scale into full-day profit. Second, a forced end-of-day flatten or generic trailing stop reduced drawdown but often removed the later reversion or settlement value that the strategy needed.

I moved from a single headline PnL number to full-day, per-product, drawdown, and stress comparisons. The final version was a balanced inventory-and-premium strategy. It gave up some raw backtest profit to reduce concentration in late voucher positions.

## Round 5

### 1. Data and Market Interpretation

Round 5 had a much larger product universe. Every product had a position limit of 10. I grouped products by family and measured daily drift, intraday direction, volatility, spread, trade frequency, and drawdown.

The live logs were especially important. They showed that many real fills occurred when an inside quote was hit by a market trade. A backtester that waited for the best quote to cross the limit price missed this behavior. At the same time, the logs showed that deep quotes did not receive the optimistic fills predicted by an early event model.

The data also showed that cross-day direction labels could fail within a day. A product could have a higher daily average price but still fall for most of the session. This was the main explanation for the weaker Round 5 day-four results.

### 2. Strategy Choice

I built a cap-safe directional book for products with stable evidence across days. Quotes were placed inside the spread only where the live fill mechanism supported it.

I used family-level controls for related risks. The PEBBLES basket had a useful price identity, but its short-lived deviations were too fast to support a large standalone mean-reversion strategy. It became a small, cap-safe overlay rather than the main source of return.

I added narrow risk gates where the data supported them. For example, `MICROCHIP_SQUARE` was disabled only when an early relative-price move resembled the day-four reversal pattern. I did not remove every product with one bad day.

### 3. Backtest Findings and Revisions

Round 5 forced the largest changes to my research process. The original backtester used an unrealistic fill rule. It also exposed an order-limit bug in the PEBBLES overlay. Both issues made early results unreliable.

I replaced the fill logic with a trade-driven model and then made it stricter for non-inside quotes. I added per-tick order reservation so base orders and overlays could not exceed the limit together. I then evaluated each module by day, drawdown, and live-log fit rather than by total PnL alone.

This process overturned several earlier conclusions. More products did not automatically create a better portfolio. Symmetric market making was not a default expansion path. A high backtest return from a product with poor live fills was not credible. The final Round 5 strategy favored fewer validated modules and targeted tail-risk controls.

## Main Lessons

- A market signal must be executable, not only statistically visible.
- A fill model is part of the strategy. If it is wrong, the backtest is wrong.
- Product-level returns can hide family-level risk.
- A good strategy should be evaluated across days and market regimes, not by one strong result.
- Risk controls should address a diagnosed failure mode. Broad defensive rules can remove the alpha as well as the risk.

## Scope Note

I checked product names, position limits, and round rules against a public Prosperity 4 write-up. I used it only to validate the competition context. The analysis, implementation, and strategy decisions in these notes were developed independently.
