"""Put / call credit spreads (trading sleeve, defined-risk short premium).

Stage 5. 30-60 DTE (target 45); short strike ~16-30 delta (default 20); width
sized so defined max-loss fits the per-position budget. Per-stock IVR floor 30.
Management metadata: PT 50% max profit; stop 2x credit; must-touch-by 21 DTE;
short-strike-test alert.
"""
