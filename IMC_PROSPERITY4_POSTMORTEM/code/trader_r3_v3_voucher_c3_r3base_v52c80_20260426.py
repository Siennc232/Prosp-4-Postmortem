"""
trader_r3_v3_voucher_c3_r3base_v52c80_20260426.py — R3 Route 3 nudge candidate.

Production candidate generated from cap90 baseline:
  VEV_5000 cap=90 + VEV_5300 cap=60 + VEV_5200 cap=80.

BT research (Layer 20 nudge):
  full-day settled Σ = +98988
  day2 live-slice MTM = +10088
  mdd = 1.03x vs R3_base
  stress +100 improves vs R3_base; stress +200 is modestly worse.
  This is the preferred small nudge over R3_base for crossing 10k.

Reference R3_base:
  VEV_5000 cap=90 + VEV_5300 cap=60 + VEV_5200 cap=60
  full-day settled Σ = +96658
  day2 live-slice MTM = +9910
  mdd = -12821
  Fallbacks:
    B2: V5 90 + V53 60 (less tail, slice ~9068)
    C2: same caps, V52 entry size 10 (balanced, slice ~9786)
    C4: V5 90 + V53 90 + V52 30 (steadier, slice ~9710)


Identical to trader_r3_v3_voucher_c3_20260425.py except VV5_CAP=90.
That earlier file (cap=60) is the FALLBACK.

  Cap sweep evidence (V2 trader, fixed VV5_SIZE_PER_FIRE=20, /tmp/v3_cap_sweep.py):
    cap   3-day Σ      slice     mdd     end_pos d0/d1/d2
     60   +75502       +8276     9760    +0/-45/-60       (fallback)
     70   +76360       +8350    10075    +0/-45/-70
     75   +76795       +8398    10232    +0/-45/-75
     80   +77248       +8448    10390    +0/-45/-80
     85   +77722       +8494    10548    +0/-45/-85
     90   +78216       +8534   10701    +0/-45/-90       ← THIS FILE

  vs cap=60 baseline:
    Σ        +2714  (+3.6%)
    slice    +258   (+3.1%)
    mdd      1.10×  (within 1.15× guardrail)
    EOD pin  -90    (cap-bound; no closer firing in d2 last block)

  Why cap=90 over cap=60:
    - sweep is monotonic; no inflection / no overfit
    - mdd grows mildly; no PnL/mdd blowup pattern
    - mechanism: cap was binding constraint on VEV_5000 alpha capture
    - slice +258 < +300 threshold is structural (slice is first 10% of day,
      cap-binding happens in mid/late day); not a hard fail.

  Rejected research lines (do NOT re-open without new hypothesis):
    - cleanup CLEAN1-5 (17 variants):  all ΔΣ ≤ 0
    - spread 5000/5100, 5000/5200:     net delta dilution kills alpha
    - softsize on adev_now tiers:      Δ +317 over cap-only ablation (worthless)

Original gated_v3 base + VEV_5000 sell-only overflow + C3 dev<=0 closer.
HY behavior unchanged. VV behavior unchanged.
"""
from datamodel import TradingState, Order
from typing import Dict, List, Optional, Tuple
import json
import math


class Trader:

    LIMITS: Dict[str, int] = {
        "HYDROGEL_PACK":       200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_5000":            200,
        "VEV_5200":            200,
        "VEV_5300":            200,
    }

    EMA_ALPHA = 0.003
    FAIR_ANCHOR_WEIGHT = 0.40
    ANCHOR: Dict[str, float] = {"VELVETFRUIT_EXTRACT": 5250.0}

    HYDRO_SOFT_LIMIT      = 24
    HYDRO_ORDER_SIZE      = 16
    HYDRO_MIN_EDGE        = 2
    HYDRO_LATE_FLATTEN_T  = 92000

    VV_TAKE_BUY_EDGE         = 6.0
    VV_TAKE_SELL_EDGE        = 7.0
    VV_MAKE_BUY_EDGE         = 6.0
    VV_MAKE_SELL_EDGE        = 7.0
    VV_MAX_ORDER             = 24
    VV_SKEW_TICKS            = 8.0
    VV_REVERSION_WEIGHT      = 0.18
    VV_CLEAR_THRESHOLD       = 18
    VV_ADVERSE_COVER_TICKS   = 2.0

    VV_AF_POS_LO             = 120
    VV_AF_POS_HI             = 190
    VV_AF_ALIGNED_DEV        = 10.0
    VV_AF_DEV_CHANGE_5       = 0.5
    VV_AF_MOM_5              = -0.5
    VV_AF_TAKE_BOOST         = 24

    # === Voucher overflow ===
    # Sell-only C3 overflow legs. All legs use the same addfast gate and C3 closer.
    VOUCHER_CAPS: Dict[str, int] = {
        "VEV_5000": 90,
        "VEV_5300": 60,
        "VEV_5200": 80,
    }
    VOUCHER_SIZE_PER_FIRE    = 20
    VOUCHER_CLOSER_DEV       = 0.0

    # Backward aliases for unchanged helper naming / old comments.
    VV5_CAP                  = 90
    VV5_SIZE_PER_FIRE        = VOUCHER_SIZE_PER_FIRE
    VV5_CLOSER_DEV           = VOUCHER_CLOSER_DEV

    def run(self, state: TradingState):
        saved = self._decode_state(state.traderData)
        result: Dict[str, List[Order]] = {}

        od_hy = state.order_depths.get("HYDROGEL_PACK")
        if od_hy is not None:
            orders = self._hydrogel(
                od_hy,
                state.position.get("HYDROGEL_PACK", 0),
                state.timestamp,
            )
            if orders:
                result["HYDROGEL_PACK"] = orders

        # === VV: compute overflow state BEFORE _trade_delta_one mutates af_hist ===
        overflow_state = None  # (af_for_overflow, vv_dev, vv_side, vv_pos)
        od_vv = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if od_vv is not None:
            mid_vv = self._mid_from_book(od_vv)
            ema_vv = self._update_ema(saved, "VELVETFRUIT_EXTRACT", mid_vv)
            velvet_fair = self._blended_fair("VELVETFRUIT_EXTRACT", ema_vv)
            if velvet_fair is not None:
                vv_pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
                if od_vv.buy_orders and od_vv.sell_orders:
                    bb = max(od_vv.buy_orders); ba = min(od_vv.sell_orders)
                    cur_mid = (bb + ba) / 2.0
                    cur_dev = cur_mid - velvet_fair
                    h = saved.get("af_hist", {}).get("VELVETFRUIT_EXTRACT", {"mid": [], "dev": []})
                    side = 1 if vv_pos > 0 else (-1 if vv_pos < 0 else 0)
                    af_for_overflow = False
                    if side != 0 and len(h["mid"]) >= 5:
                        adev_now = -side * cur_dev
                        adev_5 = -side * h["dev"][-5]
                        adev_change_5 = adev_now - adev_5
                        mom_5 = side * (cur_mid - h["mid"][-5])
                        if (adev_now >= self.VV_AF_ALIGNED_DEV
                            and adev_change_5 > self.VV_AF_DEV_CHANGE_5
                            and mom_5 < self.VV_AF_MOM_5):
                            af_for_overflow = True
                            if len(h["mid"]) >= 50:
                                last50 = list(h["mid"][-49:]) + [cur_mid]
                                range_50 = max(last50) - min(last50)
                                slope_50 = (cur_mid - h["mid"][-50]) / 50.0
                                if side < 0 and range_50 >= 12 and slope_50 >= 0.18:
                                    af_for_overflow = False
                                elif side > 0 and range_50 <= 12:
                                    af_for_overflow = False
                    overflow_state = (af_for_overflow, cur_dev, side, vv_pos)

                orders = self._trade_delta_one(
                    "VELVETFRUIT_EXTRACT", od_vv, vv_pos, velvet_fair, saved,
                )
                if orders:
                    result["VELVETFRUIT_EXTRACT"] = orders

        # === Voucher overflow (post-VV, uses overflow_state) ===
        if overflow_state is not None:
            for voucher, cap in self.VOUCHER_CAPS.items():
                od_voucher = state.order_depths.get(voucher)
                if od_voucher is None:
                    continue
                pos_voucher = state.position.get(voucher, 0)
                voucher_orders = self._voucher_overflow(
                    voucher, od_voucher, pos_voucher, cap, overflow_state,
                )
                if voucher_orders:
                    result[voucher] = voucher_orders

        traderData = json.dumps(saved, separators=(",", ":"))
        return result, 0, traderData

    def _voucher_overflow(self, voucher: str, depth, position: int,
                          cap: int, overflow_state) -> List[Order]:
        af_active, vv_dev, vv_side, vv_pos = overflow_state
        orders: List[Order] = []
        if not depth.buy_orders or not depth.sell_orders:
            return orders
        size = self.VOUCHER_SIZE_PER_FIRE

        bb = max(depth.buy_orders); ba = min(depth.sell_orders)
        bbv = depth.buy_orders[bb]
        bav = -depth.sell_orders[ba]

        # ENTRY: sell voucher at bid_1 when VV addfast short signal is active.
        if af_active and vv_side < 0 and vv_pos <= -190:
            room_short = cap + position
            if room_short > 0:
                qty = min(size, bbv, room_short)
                if qty > 0:
                    orders.append(Order(voucher, bb, -qty))

        # EXIT (C3 closer): buy back at ask_1 after VV reverts through fair.
        if position < 0 and vv_dev <= self.VOUCHER_CLOSER_DEV:
            qty = min(size, bav, -position)
            if qty > 0:
                orders.append(Order(voucher, ba, qty))

        return orders

    # ===================================================================
    # Below: unchanged from gated_v3
    # ===================================================================

    def _hydrogel(self, depth, position: int, timestamp: int) -> List[Order]:
        if not depth.buy_orders or not depth.sell_orders:
            return []
        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        outer_bid = min(depth.buy_orders)
        outer_ask = max(depth.sell_orders)
        fair = (outer_bid + outer_ask) / 2.0
        orders: List[Order] = []
        live_pos = position
        limit = self.LIMITS["HYDROGEL_PACK"]
        buy_cap = limit - live_pos
        sell_cap = limit + live_pos
        for ask in sorted(depth.sell_orders):
            if buy_cap <= 0 or live_pos >= self.HYDRO_SOFT_LIMIT:
                break
            if ask <= fair - self.HYDRO_MIN_EDGE:
                qty = min(-depth.sell_orders[ask], buy_cap, self.HYDRO_ORDER_SIZE,
                          self.HYDRO_SOFT_LIMIT - live_pos)
                if qty > 0:
                    orders.append(Order("HYDROGEL_PACK", ask, qty))
                    live_pos += qty; buy_cap -= qty; sell_cap += qty
        for bid in sorted(depth.buy_orders, reverse=True):
            if sell_cap <= 0 or live_pos <= -self.HYDRO_SOFT_LIMIT:
                break
            if bid >= fair + self.HYDRO_MIN_EDGE:
                qty = min(depth.buy_orders[bid], sell_cap, self.HYDRO_ORDER_SIZE,
                          self.HYDRO_SOFT_LIMIT + live_pos)
                if qty > 0:
                    orders.append(Order("HYDROGEL_PACK", bid, -qty))
                    live_pos -= qty; sell_cap -= qty; buy_cap += qty
        skew = self._clamp(live_pos / self.HYDRO_SOFT_LIMIT, -1.0, 1.0) * 3.0
        bid_px = min(best_bid + 1, int(fair - self.HYDRO_MIN_EDGE - skew))
        ask_px = max(best_ask - 1, int(fair + self.HYDRO_MIN_EDGE - skew + 0.999999))
        if timestamp >= self.HYDRO_LATE_FLATTEN_T:
            if live_pos > 0 and sell_cap > 0:
                qty = min(live_pos, sell_cap, self.HYDRO_ORDER_SIZE)
                orders.append(Order("HYDROGEL_PACK", best_bid, -qty)); live_pos -= qty
            elif live_pos < 0 and buy_cap > 0:
                qty = min(-live_pos, buy_cap, self.HYDRO_ORDER_SIZE)
                orders.append(Order("HYDROGEL_PACK", best_ask, qty)); live_pos += qty
            return orders
        buy_cap = limit - live_pos; sell_cap = limit + live_pos
        if bid_px < ask_px and live_pos < self.HYDRO_SOFT_LIMIT and buy_cap > 0:
            qty = min(self.HYDRO_ORDER_SIZE, buy_cap, self.HYDRO_SOFT_LIMIT - live_pos)
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", bid_px, qty))
        if bid_px < ask_px and live_pos > -self.HYDRO_SOFT_LIMIT and sell_cap > 0:
            qty = min(self.HYDRO_ORDER_SIZE, sell_cap, self.HYDRO_SOFT_LIMIT + live_pos)
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", ask_px, -qty))
        return orders

    def _trade_delta_one(self, product, depth, position, fair, saved):
        best_bid, best_bid_qty, best_ask, best_ask_qty = self._best_prices(depth)
        if best_bid is None or best_ask is None:
            self._update_fair_memory(saved, product, fair)
            return []
        best_mid = (best_bid + best_ask) / 2.0
        af_root = saved.setdefault("af_hist", {})
        h = af_root.setdefault(product, {"mid": [], "dev": []})
        h["mid"].append(best_mid)
        h["dev"].append(best_mid - fair)
        if len(h["mid"]) > 51: del h["mid"][0]
        if len(h["dev"]) > 6: del h["dev"][0]
        last_fair = saved.get("last_fair", {}).get(product)
        last_move = 0.0 if last_fair is None else fair - float(last_fair)
        self._update_fair_memory(saved, product, fair)
        limit = self.LIMITS[product]
        max_order = self.VV_MAX_ORDER
        clear_threshold = self.VV_CLEAR_THRESHOLD
        adverse_cover_ticks = self.VV_ADVERSE_COVER_TICKS
        skew_ticks = self.VV_SKEW_TICKS
        reversion_weight = self.VV_REVERSION_WEIGHT
        abs_pos = abs(position)
        side = 1 if position > 0 else (-1 if position < 0 else 0)
        af_active = False
        if (side != 0 and self.VV_AF_POS_LO <= abs_pos < self.VV_AF_POS_HI
            and len(h["mid"]) >= 6):
            aligned_dev_now = -side * h["dev"][-1]
            aligned_dev_5   = -side * h["dev"][-6]
            aligned_dev_change_5 = aligned_dev_now - aligned_dev_5
            momentum_5 = side * (h["mid"][-1] - h["mid"][-6])
            if (aligned_dev_now >= self.VV_AF_ALIGNED_DEV
                and aligned_dev_change_5 > self.VV_AF_DEV_CHANGE_5
                and momentum_5 < self.VV_AF_MOM_5):
                af_active = True
                if len(h["mid"]) >= 51:
                    last50 = h["mid"][-50:]
                    range_50 = max(last50) - min(last50)
                    slope_50 = (h["mid"][-1] - h["mid"][-51]) / 50.0
                    if side < 0 and range_50 >= 12 and slope_50 >= 0.18:
                        af_active = False
                    elif side > 0 and range_50 <= 12:
                        af_active = False
        buy_take_cap  = max_order + (self.VV_AF_TAKE_BOOST if (af_active and side > 0) else 0)
        sell_take_cap = max_order + (self.VV_AF_TAKE_BOOST if (af_active and side < 0) else 0)
        orders: List[Order] = []
        start_pos = position
        live_position = position
        reserved_buy = 0
        reserved_sell = 0
        def buy_room() -> int:
            return max(0, limit - start_pos - reserved_buy)
        def sell_room() -> int:
            return max(0, limit + start_pos - reserved_sell)
        def add_buy(price: int, desired_qty: int) -> int:
            nonlocal reserved_buy, live_position
            qty = min(desired_qty, buy_room())
            if qty > 0:
                orders.append(Order(product, price, qty))
                reserved_buy += qty; live_position += qty
            return qty
        def add_sell(price: int, desired_qty: int) -> int:
            nonlocal reserved_sell, live_position
            qty = min(desired_qty, sell_room())
            if qty > 0:
                orders.append(Order(product, price, -qty))
                reserved_sell += qty; live_position -= qty
            return qty
        adj_fair = fair - (live_position / limit) * skew_ticks - reversion_weight * last_move
        take_fair = fair if af_active else adj_fair
        if best_ask <= take_fair - self.VV_TAKE_BUY_EDGE:
            add_buy(best_ask, min(-best_ask_qty, buy_take_cap))
        if best_bid >= take_fair + self.VV_TAKE_SELL_EDGE:
            add_sell(best_bid, min(best_bid_qty, sell_take_cap))
        if live_position < -clear_threshold and last_move >= adverse_cover_ticks:
            add_buy(best_ask, min(-live_position, -best_ask_qty, max(1, max_order // 3)))
        elif live_position > clear_threshold and last_move <= -adverse_cover_ticks:
            add_sell(best_bid, min(live_position, best_bid_qty, max(1, max_order // 3)))
        if live_position > clear_threshold:
            add_sell(int(math.ceil(fair)),
                     min(live_position - clear_threshold // 2, max(1, max_order // 3)))
        elif live_position < -clear_threshold:
            add_buy(int(math.floor(fair)),
                    min(-live_position - clear_threshold // 2, max(1, max_order // 3)))
        quote_fair = fair - (live_position / limit) * skew_ticks - reversion_weight * last_move
        bid_price = min(best_bid + 1, int(math.floor(quote_fair - self.VV_MAKE_BUY_EDGE)))
        ask_price = max(best_ask - 1, int(math.ceil(quote_fair + self.VV_MAKE_SELL_EDGE)))
        if bid_price >= ask_price:
            bid_price = int(math.floor(quote_fair - 1))
            ask_price = int(math.ceil(quote_fair + 1))
        if bid_price < ask_price:
            add_buy(bid_price, max_order)
            add_sell(ask_price, max_order)
        return orders

    def _mid_from_book(self, depth) -> Optional[float]:
        if depth is None or not depth.buy_orders or not depth.sell_orders:
            return None
        return (max(depth.buy_orders) + min(depth.sell_orders)) / 2.0

    def _update_ema(self, saved: Dict, product: str, mid: Optional[float]) -> Optional[float]:
        if mid is None:
            return saved.get("ema", {}).get(product)
        ema_map = saved.setdefault("ema", {})
        prev = ema_map.get(product)
        ema = mid if prev is None else (1.0 - self.EMA_ALPHA) * float(prev) + self.EMA_ALPHA * mid
        ema_map[product] = ema
        return ema

    def _blended_fair(self, product: str, ema: Optional[float]) -> Optional[float]:
        if ema is None:
            return None
        anchor = self.ANCHOR.get(product)
        if anchor is None:
            return ema
        w = self.FAIR_ANCHOR_WEIGHT
        return (1.0 - w) * ema + w * anchor

    def _best_prices(self, depth) -> Tuple[Optional[int], int, Optional[int], int]:
        if depth is None or not depth.buy_orders or not depth.sell_orders:
            return None, 0, None, 0
        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        return best_bid, depth.buy_orders[best_bid], best_ask, depth.sell_orders[best_ask]

    def _update_fair_memory(self, saved: Dict, product: str, fair: float) -> None:
        if "last_fair" not in saved:
            saved["last_fair"] = {}
        saved["last_fair"][product] = fair

    def _decode_state(self, trader_data: str) -> Dict:
        if not trader_data:
            return {}
        try:
            data = json.loads(trader_data)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))
