"""Covered call on SMSF core shares (wheel exit leg).

Stage 7. 30-45 DTE, ~15-25 delta (low, rarely called away); roll at 21 DTE or
80% profit; skip a cycle if strike straddles earnings or sits in an ex-div
assignment-risk window (extrinsic < dividend).
"""
