"""Cash-secured put (SMSF wheel, accumulation).

Stage 7. 30-45 DTE, ~20-30 delta (assignment desired), strike at/below
acquire_below_price when set, never straddling confirmed earnings, cash reserved
= strike*100. Management: PT 50% -> close & redeploy, or allow assignment; roll
only to avoid assignment when the stock isn't wanted yet.
"""
