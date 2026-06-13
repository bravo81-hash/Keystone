"""EOD position monitor (fast clock). Monitors OPEN positions only.

Stage 11. Per position: mark + P&L vs entry; short-leg delta/moneyness; DTE;
distance underlying->short strike in ATR units; assignment-risk flags; pin-risk;
earnings-gap detection. Portfolio-level: budget utilization, sector
concentration, correlation, beta-mapped stress refresh.
"""
