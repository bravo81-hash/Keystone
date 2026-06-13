"""Weekly liquidity screen -> universe/screened.json.

Stage 1. Uses ib_client cached Friday chains (2-pass ATM + 25-delta fetch).
Hard gates: ATM spread, 4 consecutive weekly expiries, last price >= $30,
option ADV/OI, confirmed earnings (else hard skip), SMSF affordability flags.
Consumers treat screened.json older than 7 days as empty.
"""
