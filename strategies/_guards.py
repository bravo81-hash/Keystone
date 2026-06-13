"""american_guards(ctx) — shared validity checks run by every strategy.

Stage 5. No short leg in an expiry that STRADDLES a confirmed earnings date
(names; ETFs exempt); short call with ex-div before expiry and extrinsic <
dividend is invalid; pin-risk note when short strike within 0.5*20d ATR at
<= 2 DTE (card warning, not a block).
"""
