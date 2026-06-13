"""Alert triggers + severity.

Stage 11. INFO (profit target 50% hit), WARN (approaching stop, must-touch-by
DTE, short strike within X*ATR, roll due), CRITICAL (stop breached, short strike
breached, assignment imminent, regime flipped HARD_SKIP, pin risk). Each alert
carries a suggested action and links to execution.stage_to_tws + OptionStrat.
"""
