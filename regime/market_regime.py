"""Market regime gate (the on/off switch).

Stage 4. Term structure from VIX9D/VIX/VIX3M (contango/backwardation) + trend
filter (broad index vs rising/falling 200DMA). Output a state with an explicit
HARD_SKIP set and a DEFENSIVE set.
"""
