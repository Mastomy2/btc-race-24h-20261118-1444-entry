"""BTC trend bot for make.fun btc-race-24h-20261118-1444.

Speaks agent-fun/bars-replay/v1 (NDJSON stdin/stdout) through the vendored
kit shim. Long only, one symbol (CBBTC), at most one open position, full size.

Strategy (fresh logic, written for this competition):
  * Entry, only in an up regime: the 60-bar return beats MOM60_BPS, the
    close breaks above the highest close of the previous BREAKOUT_BARS bars
    by at least BO_MARGIN_BPS, the fast EMA is above the slow EMA, and the
    slow EMA is rising. (REGIME_BARS > 0 would additionally require the
    close above a long EMA; the 240-bar return cap MOM240_MAX_BPS and the
    RSI dip entry are both disabled in the tuned configuration, because on
    the dev window they either never fired or blocked the winning trade.)
    All must agree, so entries fire only at the start of a sustained
    up-leg, not on 1-minute noise: on the dev window this fires exactly
    once, at the foot of the day's +2% up-leg.
  * Dip entry (RSI_DIP >= 0 only): RSI(14) under RSI_DIP while the slow EMA
    is not falling and the close ticks up from the previous bar.
  * Exits, whole position: take-profit at TP_BPS over cost, stop-loss at
    SL_BPS under cost, trailing stop TRAIL_BPS under the peak value since
    entry, and (when EXIT_CROSS is 1) the fast EMA crossing back under the
    slow EMA. After any exit, no new entry for COOLDOWN_BARS bars, so a
    take-profit exit at a leg top is not chased straight back in.
  * No new entries in the last NO_ENTRY_AFTER_SEQ bars (the flatten at the
    window end costs ~13 bps, so a late entry has no time to pay for itself).

All decisions use only the bars the harness has sent (closes); no wall
clock, no randomness, no files, no network. Float64 EMA/RSI with fixed
seeding, so two runs on the same bars give byte-identical replies.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars  # noqa: E402

SYMBOL = "CBBTC"

# --- tunable parameters (tuned on the dev window with work/backtest.py) ---
# Final: one decisive trade on dev (buy bar 397, sell bar 508), +$11.38.
EMA_FAST = 8
EMA_SLOW = 72
REGIME_BARS = 0
RSI_PERIOD = 14
RSI_DIP = -1
BREAKOUT_BARS = 90
MOM_BARS = 60
MOM60_BPS = 20
MOM240_BARS = 240
MOM240_MAX_BPS = 10000
BO_MARGIN_BPS = 20
SLOPE_BARS = 10
TP_BPS = 120
SL_BPS = 60
TRAIL_BPS = 100
EXIT_CROSS = 0
COOLDOWN_BARS = 60
MAX_SLIPPAGE_BPS = 300
NO_ENTRY_AFTER_SEQ = 1380


class Ema:
    """EMA seeded as the mean of its first `span` closes, then 2/(span+1) steps."""

    def __init__(self, span):
        self.span = span
        self.warm = []
        self.value = None

    def push(self, close):
        if self.value is not None:
            self.value += (2.0 / (self.span + 1)) * (close - self.value)
            return
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span


class Series:
    """Per-symbol indicator state over closes."""

    def __init__(self):
        self.fast = Ema(EMA_FAST)
        self.slow = Ema(EMA_SLOW)
        self.regime = Ema(REGIME_BARS) if REGIME_BARS > 0 else None
        self.slow_hist = []          # slow EMA values, oldest first
        self.closes = []             # recent closes, oldest first
        self.prev_close = None
        self.rsi_first = []          # first RSI_PERIOD changes
        self.rsi_gain = None
        self.rsi_loss = None
        self.peak_value = None       # peak position value since entry (quote units)
        self.last_exit_seq = -10 ** 9  # seq of the last exit (for the cooldown)

    def push(self, bar):
        close = float(int(bar["c"])) / 1e5  # USDC, price_scale 5
        self.fast.push(close)
        self.slow.push(close)
        if self.regime is not None:
            self.regime.push(close)
        if self.slow.value is not None:
            self.slow_hist.append(self.slow.value)
            if len(self.slow_hist) > SLOPE_BARS + 1:
                self.slow_hist.pop(0)
        self.closes.append(close)
        keep = max(BREAKOUT_BARS, MOM_BARS, MOM240_BARS) + 1
        if len(self.closes) > keep:
            self.closes.pop(0)
        if self.prev_close is not None:
            change = close - self.prev_close
            if self.rsi_gain is None:
                self.rsi_first.append(change)
                if len(self.rsi_first) == RSI_PERIOD:
                    self.rsi_gain = sum(c for c in self.rsi_first if c > 0) / RSI_PERIOD
                    self.rsi_loss = sum(-c for c in self.rsi_first if c < 0) / RSI_PERIOD
            else:
                up = change if change > 0 else 0.0
                down = -change if change < 0 else 0.0
                self.rsi_gain = (self.rsi_gain * (RSI_PERIOD - 1) + up) / RSI_PERIOD
                self.rsi_loss = (self.rsi_loss * (RSI_PERIOD - 1) + down) / RSI_PERIOD
        self.prev_close = close

    def rsi(self):
        if self.rsi_gain is None:
            return None
        moved = self.rsi_gain + self.rsi_loss
        return 50.0 if moved == 0 else 100.0 * self.rsi_gain / moved

    def slow_slope(self):
        """Slow EMA now vs SLOPE_BARS bars ago, as a fraction (None if not ready)."""
        if len(self.slow_hist) < SLOPE_BARS + 1:
            return None
        old = self.slow_hist[0]
        return (self.slow_hist[-1] - old) / old if old else 0.0

    def breakout(self):
        """True when the latest close beats every close of the previous
        BREAKOUT_BARS by at least BO_MARGIN_BPS."""
        if len(self.closes) < BREAKOUT_BARS + 1:
            return False
        prev_high = max(self.closes[-BREAKOUT_BARS - 1:-1])
        return (self.closes[-1] - prev_high) * 10000.0 >= BO_MARGIN_BPS * prev_high

    def momentum_bps(self, bars=MOM_BARS):
        """Return over the last `bars` bars, in bps (None if not ready)."""
        if len(self.closes) < bars + 1:
            return None
        old = self.closes[-bars - 1]
        return (self.closes[-1] - old) / old * 10000.0 if old else 0.0


SERIES = {}


def on_batch(state, batch):
    for bar in batch["bars"]:
        s = SERIES.setdefault(bar["symbol"], Series())
        s.push(bar)
    if state.warming_up:
        return []
    s = SERIES.get(SYMBOL)
    if s is None:
        return []
    held = state.positions.get(SYMBOL)
    close = state.close(SYMBOL)
    if close is None:
        return []

    if held is not None:
        value = state.value(SYMBOL, held.qty)
        if s.peak_value is None or value > s.peak_value:
            s.peak_value = value
        cost = held.cost
        tp = value * 10000 >= cost * (10000 + TP_BPS)
        sl = value * 10000 <= cost * (10000 - SL_BPS)
        trail = s.peak_value is not None and value * 10000 <= s.peak_value * (10000 - TRAIL_BPS)
        cross_down = (EXIT_CROSS == 1 and s.fast.value is not None
                      and s.slow.value is not None
                      and s.fast.value < s.slow.value)
        if tp or sl or trail or cross_down:
            s.peak_value = None
            s.last_exit_seq = state.seq
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    # Flat: consider an entry.
    s.peak_value = None
    if state.seq >= NO_ENTRY_AFTER_SEQ:
        return []
    if state.seq - s.last_exit_seq < COOLDOWN_BARS:
        return []
    if s.fast.value is None or s.slow.value is None:
        return []
    if s.regime is not None and (s.regime.value is None
                                 or s.closes[-1] <= s.regime.value):
        return []
    slope = s.slow_slope()
    if slope is None or slope <= 0:
        return []
    mom = s.momentum_bps()
    if mom is None or mom < MOM60_BPS:
        return []
    mom240 = s.momentum_bps(MOM240_BARS)
    if mom240 is None or mom240 >= MOM240_MAX_BPS:
        return []
    rsi = s.rsi()
    breakout = (s.breakout() and s.fast.value > s.slow.value)
    dip = (RSI_DIP >= 0 and rsi is not None and rsi < RSI_DIP
           and len(s.closes) >= 2 and s.closes[-1] > s.closes[-2])
    if not (breakout or dip):
        return []
    room = state.weight_room(SYMBOL)
    notional = state.cash if state.cash < room else room
    if notional < int(state.hello["fees"]["min_notional_quote_units"]):
        return []
    return [{"side": "buy", "symbol": SYMBOL,
             "notional_quote_units": notional,
             "max_slippage_bps": MAX_SLIPPAGE_BPS}]


makefun_bars.run(on_batch)
