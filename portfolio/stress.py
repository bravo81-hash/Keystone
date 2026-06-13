"""Portfolio stress.

Stage 8. Full-book market row: -5% spot / IV+10 / 2d, beta-mapped per name (60d
beta vs SPY from cached daily history). PLUS worst-single-name row: -15% gap /
IV+15 (use +/-1.5x implied move if inside an earnings window). Stress ceiling
calibrated to THIS book's expected weekly/monthly P&L (configurable).
"""
