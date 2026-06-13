"""IV history + realized vol.

Stage 3. reqHistoricalData OPTION_IMPLIED_VOLATILITY 1yr daily, one req/ticker/
week, cached -> IVR + IV percentile. Realized vol 20d close-to-close from daily
TRADES history (cache shared with Stage 2 realized-moves). VRP = IV30 - RV20.
"""
