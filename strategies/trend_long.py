"""Long-premium trend convexity (trading sleeve, small).

Stage 6. Proposes LEAPS (deep ITM ~70-80 delta) stock-replacement, a diagonal
(long LEAPS + short ~30 delta monthly call), or a long vertical debit spread
(60-120 DTE). Size <= 0.5% NLV/position; aggregate trend-sleeve ceiling 5% NLV.
Management: trail underlying stop (trend invalidation) -> alert; diagonal short
call rolled monthly or at 80% profit; NO profit target on the long leg. The
diagonal construction is reused by SMSF PMCC (Stage 7) behind a config flag.
"""
