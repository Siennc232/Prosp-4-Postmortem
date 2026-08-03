"""
Round 4 ship candidate: HY ship + VEV_5300/VEV_5500 high-premium hold overlays.

Base = trader_r4_mark67_delay70_v5strong_ladder_20260426.py.

Confirmed HY changes:
  - HY late flatten moves from 92k to 999.9k.
  - HY order size uses the best replay setting, 8.
  - Base HY soft cap remains 24.
  - A side may expand to cap 40 only when side * HY 100k mid drift <= 12.
  - HY inventory skew still uses cap24, so capacity is relaxed without making
    quotes less inventory-aware.

Voucher premium overlay:
  - Short VEV_5300 at the best bid only when bid >= 52.
  - Hold-to-settlement cap is 200 contracts.
  - Also short VEV_5500 at the best bid only when bid >= 7.
  - VEV_5500 is a low-delta premium add-on that improved all three days in
    local replay.

VV time template:
  - Before timestamp 50k, keep the original VV take/make edges 6/7.
  - From timestamp 50k onward, require one extra tick on all VV take/make
    edges.  Replay fine sweep improved all three days without increasing MDD.

Conditional late voucher retention:
  - Always retain existing VEV_5400 shorts after timestamp 950k.
  - Retain existing VEV_5200/VEV_5300 shorts after timestamp 950k only if the
    day2-like classifier has activated and pinned-danger has not activated.
  - The classifier uses only current/past book, Mark67 public flow, and our
    current positions.

Day2-like V52 premium rebid:
  - In day2-like / no-pinned state, after timestamp 500k, add VEV_5200 shorts
    up to cap 200 only when best bid >= 90.
  - Fine replay showed the edge lives in the late V52 premium rebound; lower
    V52 bid thresholds are harmful.
  - Balanced version: after timestamp 990k, cover only VEV_5200 back to -140
    to recover part of the stress while keeping most of the raw edge.
"""
from bisect import bisect_left
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
        "VEV_5400":            200,
        "VEV_5500":            300,
    }

    EMA_ALPHA = 0.003
    FAIR_ANCHOR_WEIGHT = 0.40
    ANCHOR: Dict[str, float] = {"VELVETFRUIT_EXTRACT": 5250.0}

    HYDRO_SOFT_LIMIT      = 24
    HYDRO_OVERCAP_LIMIT   = 40
    HYDRO_ORDER_SIZE      = 8
    HYDRO_MIN_EDGE        = 2
    HYDRO_LATE_FLATTEN_T  = 999900
    HYDRO_DRIFT_WINDOW    = 100000
    HYDRO_DRIFT_THRESHOLD = 12.0
    V53_HOLD_CAP          = 200
    V53_HOLD_MIN_BID      = 52
    V53_HOLD_SIZE         = 20
    V55_HOLD_CAP          = 300
    V55_HOLD_MIN_BID      = 7
    V55_HOLD_SIZE         = 20
    V54_LATE_RETAIN_T     = 950_000
    DAY2LIKE_RETAIN_T     = 950_000
    DAY2LIKE_MIN_SCORE    = 8
    DAY2LIKE_MAX_DANGER   = 3
    PINNED_DANGER_SCORE   = 6
    V52_REBID_T           = 500_000
    V52_REBID_CAP         = 200
    V52_REBID_MIN_BID     = 90
    V52_REBID_SIZE        = 20
    V52_REBID_COVER_T     = 990_000
    V52_REBID_COVER_TARGET = -140
    V52_REBID_COVER_SIZE  = 20

    VV_TAKE_BUY_EDGE         = 6.0
    VV_TAKE_SELL_EDGE        = 7.0
    VV_MAKE_BUY_EDGE         = 6.0
    VV_MAKE_SELL_EDGE        = 7.0
    VV_WIDE_EDGE_START       = 50_000
    VV_BASE_TAKE_BUY_EDGE    = 6.0
    VV_BASE_TAKE_SELL_EDGE   = 7.0
    VV_BASE_MAKE_BUY_EDGE    = 6.0
    VV_BASE_MAKE_SELL_EDGE   = 7.0
    VV_WIDE_TAKE_BUY_EDGE    = 7.0
    VV_WIDE_TAKE_SELL_EDGE   = 8.0
    VV_WIDE_MAKE_BUY_EDGE    = 7.0
    VV_WIDE_MAKE_SELL_EDGE   = 8.0
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

    BASE_VOUCHER_CAPS: Dict[str, int] = {
        "VEV_5000": 0,
        "VEV_5200": 80,
        "VEV_5300": 80,
        "VEV_5400": 40,
    }
    AGGRESSIVE_VOUCHER_CAPS: Dict[str, int] = {
        "VEV_5000": 90,
        "VEV_5200": 120,
        "VEV_5300": 120,
        "VEV_5400": 120,
    }
    VOUCHER_SIZE_PER_FIRE       = 20
    VOUCHER_CLOSER_DEV          = 0.0
    VOUCHER_CLOSER_DELAY_TICKS  = 70
    VOUCHER_CLOSER_CANCEL_DEV   = 6.0
    REGIME_ADEV_THRESHOLD       = 12.0
    REGIME_MAX_PROGRESS         = 0.97
    END_TS                      = 999900.0
    MARK67_COOLDOWN_TICKS       = 50

    VV5_SIZE_PER_FIRE        = VOUCHER_SIZE_PER_FIRE
    VV5_CLOSER_DEV           = VOUCHER_CLOSER_DEV

    def run(self, state: TradingState):
        self._r4_market_trades = state.market_trades or {}
        self._apply_vv_time_template(int(state.timestamp))
        saved = self._decode_state(state.traderData)
        self._update_day2_like_classifier(saved, state)
        self._active_saved = saved
        result: Dict[str, List[Order]] = {}
        self._update_hydro_gate_history(saved, state)

        od_hy = state.order_depths.get("HYDROGEL_PACK")
        if od_hy is not None:
            orders = self._hydrogel(
                od_hy,
                state.position.get("HYDROGEL_PACK", 0),
                state.timestamp,
            )
            if orders:
                result["HYDROGEL_PACK"] = orders

        overflow_state = None
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
                    aggressive_on = False
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
                        if side < 0 and saved.get("mark67_velvet_cd", 0) > 0:
                            af_for_overflow = False
                        progress = state.timestamp / self.END_TS
                        aggressive_on = (
                            af_for_overflow
                            and side < 0
                            and vv_pos <= -190
                            and adev_now >= self.REGIME_ADEV_THRESHOLD
                            and progress <= self.REGIME_MAX_PROGRESS
                        )
                        if aggressive_on:
                            saved["regime_adev12_notlate"] = saved.get("regime_adev12_notlate", 0) + 1
                    overflow_state = (af_for_overflow, cur_dev, side, vv_pos, aggressive_on)

                orders = self._trade_delta_one(
                    "VELVETFRUIT_EXTRACT", od_vv, vv_pos, velvet_fair, saved,
                )
                if orders:
                    result["VELVETFRUIT_EXTRACT"] = orders

        if overflow_state is not None:
            for voucher in sorted(set(self.BASE_VOUCHER_CAPS) | set(self.AGGRESSIVE_VOUCHER_CAPS)):
                od_voucher = state.order_depths.get(voucher)
                if od_voucher is None:
                    continue
                pos_voucher = state.position.get(voucher, 0)
                voucher_orders = self._voucher_overflow(
                    voucher, od_voucher, pos_voucher, overflow_state,
                )
                if voucher_orders:
                    result[voucher] = voucher_orders

        self._add_v53_hold_overlay(state, result)
        self._add_v55_hold_overlay(state, result)
        self._retain_late_voucher_shorts(state, result, {"VEV_5400"}, active=True)
        day2_like_active = bool(saved.get("clf_day2_like_active", 0)) and not bool(saved.get("clf_pinned_danger_active", 0))
        self._add_v52_rebid_overlay(state, result, active=day2_like_active)
        self._retain_late_voucher_shorts(state, result, {"VEV_5200", "VEV_5300"}, active=day2_like_active)
        self._cover_v52_rebid_tail(state, result, active=day2_like_active)

        traderData = json.dumps(saved, separators=(",", ":"))
        self._active_saved = None
        return result, 0, traderData

    def _update_day2_like_classifier(self, saved: Dict, state: TradingState) -> None:
        ts = int(state.timestamp)
        od_vv = state.order_depths.get("VELVETFRUIT_EXTRACT")
        od_hy = state.order_depths.get("HYDROGEL_PACK")
        vv_mid = self._mid_from_book(od_vv)
        hy_mid = self._mid_from_book(od_hy)
        if vv_mid is not None and "clf_vv0" not in saved:
            saved["clf_vv0"] = vv_mid
        if hy_mid is not None and "clf_hy0" not in saved:
            saved["clf_hy0"] = hy_mid

        m67_net = int(saved.get("clf_m67_vv_net", 0) or 0)
        for tr in getattr(self, "_r4_market_trades", {}).get("VELVETFRUIT_EXTRACT", []):
            qty = int(getattr(tr, "quantity", 0) or 0)
            if getattr(tr, "buyer", None) == "Mark 67":
                m67_net += qty
            elif getattr(tr, "seller", None) == "Mark 67":
                m67_net -= qty
        saved["clf_m67_vv_net"] = m67_net

        vv_delta = 0.0 if vv_mid is None else vv_mid - float(saved.get("clf_vv0", vv_mid))
        hy_delta = 0.0 if hy_mid is None else hy_mid - float(saved.get("clf_hy0", hy_mid))
        od_v53 = state.order_depths.get("VEV_5300")
        od_v55 = state.order_depths.get("VEV_5500")
        v53_bid = float(max(od_v53.buy_orders)) if od_v53 is not None and od_v53.buy_orders else 0.0
        v55_bid = float(max(od_v55.buy_orders)) if od_v55 is not None and od_v55.buy_orders else 0.0

        own_vv = int(state.position.get("VELVETFRUIT_EXTRACT", 0))
        own_v53 = int(state.position.get("VEV_5300", 0))
        own_voucher_short = sum(
            max(0, -int(state.position.get(p, 0)))
            for p in ("VEV_5000", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500")
        )
        own_non55_short = sum(
            max(0, -int(state.position.get(p, 0)))
            for p in ("VEV_5000", "VEV_5200", "VEV_5300", "VEV_5400")
        )

        day2_like = 0
        if ts >= 19_100:
            day2_like += 2 if vv_delta <= -20 else 0
            day2_like += 2 if v55_bid <= 5 else 0
            day2_like += 1 if v53_bid <= 48 else 0
            day2_like += 1 if m67_net <= 5 else 0
            day2_like += 1 if own_voucher_short >= 400 else 0
        if ts >= 50_000:
            day2_like += 3 if vv_delta <= -30 else 0
            day2_like += 1 if hy_delta >= 10 else 0
        if ts >= 100_000:
            day2_like += 1 if own_non55_short <= 80 else 0
            day2_like += 1 if own_vv >= 0 else 0

        danger = 0
        if ts >= 19_100:
            danger += 2 if v53_bid >= 52 else 0
            danger += 1 if vv_delta >= -5 else 0
            danger += 1 if v55_bid >= 6 else 0
        if ts >= 50_000:
            danger += 3 if hy_delta <= -40 else 0
        if ts >= 100_000:
            danger += 2 if own_vv <= -150 else 0
            danger += 1 if own_v53 <= -150 else 0
            danger += 1 if vv_delta > -10 else 0

        saved["clf_day2_like_score"] = day2_like
        saved["clf_pinned_danger_score"] = danger
        if ts >= 50_000 and day2_like >= self.DAY2LIKE_MIN_SCORE and danger <= self.DAY2LIKE_MAX_DANGER:
            saved["clf_day2_like_active"] = 1
        if ts >= 100_000 and danger >= self.PINNED_DANGER_SCORE:
            saved["clf_pinned_danger_active"] = 1

    def _retain_late_voucher_shorts(
        self,
        state: TradingState,
        result: Dict[str, List[Order]],
        products: set,
        active: bool,
    ) -> None:
        if not active:
            return
        cutoff = self.V54_LATE_RETAIN_T if products == {"VEV_5400"} else self.DAY2LIKE_RETAIN_T
        if int(state.timestamp) < cutoff:
            return
        for product in products:
            product_orders = result.get(product)
            if not product_orders:
                continue
            live = int(state.position.get(product, 0))
            kept: List[Order] = []
            for order in product_orders:
                qty = int(order.quantity)
                if qty > 0 and live < 0:
                    open_long_qty = max(0, qty + live)
                    if open_long_qty > 0:
                        kept.append(Order(order.symbol, order.price, open_long_qty))
                        live += open_long_qty
                    continue
                kept.append(order)
                live += qty
            if kept:
                result[product] = kept
            else:
                result.pop(product, None)

    def _apply_vv_time_template(self, timestamp: int) -> None:
        if timestamp >= self.VV_WIDE_EDGE_START:
            self.VV_TAKE_BUY_EDGE = self.VV_WIDE_TAKE_BUY_EDGE
            self.VV_TAKE_SELL_EDGE = self.VV_WIDE_TAKE_SELL_EDGE
            self.VV_MAKE_BUY_EDGE = self.VV_WIDE_MAKE_BUY_EDGE
            self.VV_MAKE_SELL_EDGE = self.VV_WIDE_MAKE_SELL_EDGE
            return
        self.VV_TAKE_BUY_EDGE = self.VV_BASE_TAKE_BUY_EDGE
        self.VV_TAKE_SELL_EDGE = self.VV_BASE_TAKE_SELL_EDGE
        self.VV_MAKE_BUY_EDGE = self.VV_BASE_MAKE_BUY_EDGE
        self.VV_MAKE_SELL_EDGE = self.VV_BASE_MAKE_SELL_EDGE

    def _add_v53_hold_overlay(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        self._add_hold_overlay(
            state,
            result,
            "VEV_5300",
            self.V53_HOLD_CAP,
            self.V53_HOLD_MIN_BID,
            self.V53_HOLD_SIZE,
        )

    def _add_v55_hold_overlay(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        self._add_hold_overlay(
            state,
            result,
            "VEV_5500",
            self.V55_HOLD_CAP,
            self.V55_HOLD_MIN_BID,
            self.V55_HOLD_SIZE,
        )

    def _add_v52_rebid_overlay(
        self,
        state: TradingState,
        result: Dict[str, List[Order]],
        active: bool,
    ) -> None:
        ts = int(state.timestamp)
        if not active or ts < self.V52_REBID_T or ts >= self.V52_REBID_COVER_T:
            return
        self._add_hold_overlay(
            state,
            result,
            "VEV_5200",
            self.V52_REBID_CAP,
            self.V52_REBID_MIN_BID,
            self.V52_REBID_SIZE,
        )

    def _cover_v52_rebid_tail(
        self,
        state: TradingState,
        result: Dict[str, List[Order]],
        active: bool,
    ) -> None:
        if not active or int(state.timestamp) < self.V52_REBID_COVER_T:
            return
        depth = state.order_depths.get("VEV_5200")
        if depth is None or not depth.sell_orders:
            return
        ask = min(depth.sell_orders)
        ask_qty = -int(depth.sell_orders[ask])
        if ask_qty <= 0:
            return
        projected = int(state.position.get("VEV_5200", 0)) + sum(
            int(order.quantity) for order in result.get("VEV_5200", [])
        )
        if projected >= self.V52_REBID_COVER_TARGET:
            return
        qty = min(
            self.V52_REBID_COVER_TARGET - projected,
            self.V52_REBID_COVER_SIZE,
            ask_qty,
            self.LIMITS["VEV_5200"] - projected,
        )
        if qty > 0:
            result.setdefault("VEV_5200", []).append(Order("VEV_5200", ask, qty))

    def _add_hold_overlay(
        self,
        state: TradingState,
        result: Dict[str, List[Order]],
        product: str,
        cap: int,
        min_bid: int,
        size: int,
    ) -> None:
        depth = state.order_depths.get(product)
        if depth is None or not depth.buy_orders:
            return
        pos = int(state.position.get(product, 0))
        already = sum(order.quantity for order in result.get(product, []))
        projected = pos + already
        room = cap + projected
        if room <= 0:
            return
        bid = max(depth.buy_orders)
        if bid < min_bid:
            return
        qty = min(room, depth.buy_orders[bid], size)
        if qty > 0:
            result.setdefault(product, []).append(Order(product, bid, -qty))

    def _voucher_overflow(self, voucher: str, depth, position: int,
                          overflow_state) -> List[Order]:
        af_active, vv_dev, vv_side, vv_pos, aggressive_on = overflow_state
        orders: List[Order] = []
        if not depth.buy_orders or not depth.sell_orders:
            return orders
        caps = self.AGGRESSIVE_VOUCHER_CAPS if aggressive_on else self.BASE_VOUCHER_CAPS
        cap = caps.get(voucher, 0)
        size = self.VOUCHER_SIZE_PER_FIRE

        bb = max(depth.buy_orders); ba = min(depth.sell_orders)
        bbv = depth.buy_orders[bb]
        bav = -depth.sell_orders[ba]

        if af_active and vv_side < 0 and vv_pos <= -190 and cap > 0:
            room_short = cap + position
            if room_short > 0:
                qty = min(size, bbv, room_short)
                if qty > 0:
                    orders.append(Order(voucher, bb, -qty))

        if position < 0:
            closer_root = getattr(self, "_active_saved", None)
            if closer_root is None:
                if vv_dev <= self.VOUCHER_CLOSER_DEV:
                    qty = min(size, bav, -position)
                    if qty > 0:
                        orders.append(Order(voucher, ba, qty))
                return orders
            states = closer_root.setdefault("voucher_closer", {})
            st = states.setdefault(voucher, {"armed": False, "age": 0})
            if vv_dev <= self.VOUCHER_CLOSER_DEV:
                st["armed"] = True
            elif vv_dev > self.VOUCHER_CLOSER_CANCEL_DEV:
                st["armed"] = False
                st["age"] = 0
            if st.get("armed"):
                st["age"] = int(st.get("age", 0)) + 1
            else:
                st["age"] = 0
            if st.get("armed") and int(st.get("age", 0)) >= self.VOUCHER_CLOSER_DELAY_TICKS:
                qty = min(size, bav, -position)
                if qty > 0:
                    orders.append(Order(voucher, ba, qty))
                    if qty >= -position:
                        st["armed"] = False
                        st["age"] = 0

        return orders

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
        buy_soft = self.HYDRO_OVERCAP_LIMIT if self._allow_hydro_overcap(+1) else self.HYDRO_SOFT_LIMIT
        sell_soft = self.HYDRO_OVERCAP_LIMIT if self._allow_hydro_overcap(-1) else self.HYDRO_SOFT_LIMIT
        for ask in sorted(depth.sell_orders):
            if buy_cap <= 0 or live_pos >= buy_soft:
                break
            if ask <= fair - self.HYDRO_MIN_EDGE:
                qty = min(-depth.sell_orders[ask], buy_cap, self.HYDRO_ORDER_SIZE,
                          buy_soft - live_pos)
                if qty > 0:
                    orders.append(Order("HYDROGEL_PACK", ask, qty))
                    live_pos += qty; buy_cap -= qty; sell_cap += qty
        for bid in sorted(depth.buy_orders, reverse=True):
            if sell_cap <= 0 or live_pos <= -sell_soft:
                break
            if bid >= fair + self.HYDRO_MIN_EDGE:
                qty = min(depth.buy_orders[bid], sell_cap, self.HYDRO_ORDER_SIZE,
                          sell_soft + live_pos)
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
        if bid_px < ask_px and live_pos < buy_soft and buy_cap > 0:
            qty = min(self.HYDRO_ORDER_SIZE, buy_cap, buy_soft - live_pos)
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", bid_px, qty))
        if bid_px < ask_px and live_pos > -sell_soft and sell_cap > 0:
            qty = min(self.HYDRO_ORDER_SIZE, sell_cap, sell_soft + live_pos)
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", ask_px, -qty))
        return orders

    def _update_hydro_gate_history(self, saved: Dict, state: TradingState) -> None:
        od = state.order_depths.get("HYDROGEL_PACK")
        mid = self._mid_from_book(od) if od is not None else None
        if mid is None:
            return
        hist = saved.setdefault("hy_gate_mid_hist", [])
        ts = int(state.timestamp)
        hist.append([ts, float(mid)])
        cutoff = ts - self.HYDRO_DRIFT_WINDOW - 1000
        while hist and int(hist[0][0]) < cutoff:
            del hist[0]

    def _hydro_signed_drift(self, side: int) -> Optional[float]:
        saved = getattr(self, "_active_saved", None)
        if saved is None:
            return None
        hist = saved.get("hy_gate_mid_hist", [])
        if not hist:
            return None
        cur_ts = int(getattr(self, "_cur_hydro_ts", hist[-1][0]))
        target = cur_ts - self.HYDRO_DRIFT_WINDOW
        pairs = [(int(t), float(m)) for t, m in hist]
        idx = bisect_left(pairs, (target, -10**9))
        if idx >= len(pairs) or pairs[idx][0] != target:
            idx -= 1
        if idx < 0:
            return None
        return side * (pairs[-1][1] - pairs[idx][1])

    def _allow_hydro_overcap(self, side: int) -> bool:
        saved = getattr(self, "_active_saved", None)
        if saved is not None:
            hist = saved.get("hy_gate_mid_hist", [])
            if hist:
                self._cur_hydro_ts = int(hist[-1][0])
        signed_drift = self._hydro_signed_drift(side)
        return signed_drift is not None and signed_drift <= self.HYDRO_DRIFT_THRESHOLD

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
                if product == "VELVETFRUIT_EXTRACT" and side < 0 and saved.get("mark67_velvet_cd", 0) > 0:
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
            saved: Dict = {}
        else:
            try:
                data = json.loads(trader_data)
                saved = data if isinstance(data, dict) else {}
            except Exception:
                saved = {}
        cd = int(saved.get("mark67_velvet_cd", 0) or 0)
        if cd > 0:
            cd -= 1
        for tr in getattr(self, "_r4_market_trades", {}).get("VELVETFRUIT_EXTRACT", []):
            if getattr(tr, "buyer", None) == "Mark 67":
                cd = max(cd, self.MARK67_COOLDOWN_TICKS)
        saved["mark67_velvet_cd"] = cd
        return saved

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))
