"""stage_to_tws — the single entrypoint the UI and alerts call.

Builds the N-leg combo, runs the whatIf check (logging to the store), prepares
the OptionStrat deep link, and returns the staged (UNTRANSMITTED) order. Never
transmits — manual transmit happens in TWS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.models import Suggestion
from execution.n_leg_combo import StagedOrder, build_combo
from execution.optionstrat_links import optionstrat_url
from execution.whatif import WhatIfResult, run_whatif


@dataclass
class StageResult:
    staged_order: StagedOrder
    whatif: WhatIfResult
    optionstrat_url: str
    accepted: bool


def stage_to_tws(
    ib_client: Any,
    suggestion: Suggestion,
    *,
    db: Any = None,
    quantity: int = 1,
) -> StageResult:
    """Stage a suggestion: combo -> whatIf -> links. transmit=False throughout."""

    order = build_combo(suggestion, quantity=quantity)
    assert order.transmit is False, "staged orders must never transmit"
    whatif = run_whatif(ib_client, order, suggestion, db=db)
    return StageResult(
        staged_order=order,
        whatif=whatif,
        optionstrat_url=optionstrat_url(suggestion),
        accepted=whatif.accepted,
    )
