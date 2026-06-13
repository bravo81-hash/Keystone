"""Earnings calendar with source priority.

Stage 2. Priority: IBKR reqFundamentalData -> Finnhub (FINNHUB_KEY env) ->
data/earnings_manual.csv (overrides both). Unconfirmed/missing => confirmed=False;
callers hard-skip expiries that straddle a confirmed earnings date.
"""
