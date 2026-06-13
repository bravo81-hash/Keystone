"""Poor-man's covered call — SMSF capital-efficient core-replacement. DEFAULT OFF.

A thin wrapper over the trend_long diagonal: LEAPS ~70-80 delta long call + short
~20-30 delta monthly call, rolled monthly. Gated behind ctx.pmcc_enabled (config
``investing.pmcc_enabled``, default False). Sized by the SMSF buckets (Stage 8),
not the trading trend sleeve, so the sleeve cap is not enforced here.
"""

from __future__ import annotations

from typing import Optional

from core.context import TradeContext
from core.models import Family, Right, Suggestion
from strategies.trend_long import build_diagonal

LONG_DELTA = 0.75  # ~70-80 delta LEAPS
SHORT_DELTA = 0.25  # ~20-30 delta monthly call


def propose(ctx: TradeContext) -> Optional[Suggestion]:
    if not ctx.pmcc_enabled:
        return None  # PMCC family is OFF by default
    return build_diagonal(
        ctx,
        Right.CALL,
        long_delta=LONG_DELTA,
        short_delta=SHORT_DELTA,
        family=Family.PMCC,
        enforce_sleeve_cap=False,
    )
