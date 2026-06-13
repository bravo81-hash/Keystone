"""Earnings-premium machinery (built early, no caller in v1).

Stage 2. Implied earnings move = front ATM straddle vs total-variance baseline
excluding the event. realized_moves(symbol) = last 8 quarters |close->open|
(median). Used only by a future EVENT family — see design doc SS12.
"""
