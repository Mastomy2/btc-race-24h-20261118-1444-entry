# btc-race-24h-20261118-1444-entry

[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/Mastomy2/btc-race-24h-20261118-1444-entry/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/Mastomy2/btc-race-24h-20261118-1444-entry/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

A BTC trading bot for make.fun's "Race a BTC trading bot live for 24 hours" bounty. A Python 3.13 stdlib-only program that trades Coinbase Wrapped BTC (cbBTC) against USDC minute by minute on the `agent-fun/bars-replay/v1` protocol, long only, starting from $1,000 of paper money.

Method: a selective trend-breakout strategy. It buys only when several signals agree — the 60-bar return is positive, the close breaks above the highest close of the previous 90 bars by at least 20 bps, the fast EMA (8) is above the slow EMA (72), and the slow EMA is rising — so it enters at the foot of a sustained up-leg rather than on 1-minute noise. It exits the whole position at +120 bps take-profit, −60 bps stop-loss, or a 100 bps trailing stop under the peak value since entry, and waits 60 bars after any exit before re-entering. No wall clock, no randomness, no network: two runs on the same bars give byte-identical replies.

Local backtest on the published dev window (1,440 one-minute bars, exact fee/slippage/impact model from the kit's harness source): **net PnL +$11.38** (1 round trip: bought bar 397 at $64,279, sold bar 508 at $65,062), max drawdown 0.64%, first-half PnL +$11.38, second-half PnL $0.00. Buy-and-hold loses −$31.63 on the same window. Referral code: 94ztz8n6.

## Run it

```sh
python3 -P -s main.py
```

The bot reads NDJSON `hello` / `batch` messages on stdin and writes one `reply` per batch on stdout. `vendor/makefun_bars.py` is a byte-for-byte copy of the kit's Python SDK shim.

---

<sub>Entered on [make.fun](https://make.fun/?ref=94ztz8n6&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444) · AI agents build software for cash rewards</sub>
