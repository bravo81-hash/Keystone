"""Regime blend + hard-skip veto.

Stage 4. Stock entry score = 0.4*market + 0.6*stock_regime. Market HARD_SKIP
vetoes ALL new entries in both sleeves (never softened by forced cadence).
DEFENSIVE raises a flag the SMSF collar logic consumes (Stage 7). Earnings
proximity tags expiry pairs STRADDLES/PRE/POST/NONE; STRADDLES invalid for all
families (no EVENT family in v1).
"""
