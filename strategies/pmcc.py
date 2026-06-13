"""Poor-man's covered call (SMSF core-replacement). DEFAULT OFF.

Stage 7. Thin wrapper over the trend_long diagonal (LEAPS ~70-80 delta + short
~20-30 delta monthly call, monthly roll). Behind config flag pmcc_enabled,
default False.
"""
