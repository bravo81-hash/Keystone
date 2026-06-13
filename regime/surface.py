"""Per-stock vol surface from cached Friday chains.

Stage 3. Interpolate ATM IV at 9d/30d/90d constant tenors (total-variance
interpolation). Emit slope_9_30, slope_30_90, inverted_front.
"""
