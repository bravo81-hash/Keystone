"""The uniform Engine interface every v2 return source implements.

An Engine wraps one or more strategy modules behind a single contract so the
ranker can route candidates per engine and the governor can size each engine
against its risk budget:

  * ``name``                — "income" | "core" | "overlay"
  * ``propose(ctx)``        — list[Suggestion], each tagged with ``engine=name``
  * ``current_risk(items)`` — modeled risk contribution ($ defined max-loss) of
                              THIS engine's items (open positions or candidates)
  * ``target_allocation(engines_cfg)`` — capital fraction from engines.yaml

``risk_contribution`` is provided as an alias of ``current_risk``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional

from config.schema import EnginesConfig
from core.context import TradeContext
from core.models import Suggestion


def tag_engine(suggestions: Iterable[Optional[Suggestion]], engine: str) -> list[Suggestion]:
    """Stamp ``engine`` on each non-None suggestion; drop Nones. Returns a list."""

    out: list[Suggestion] = []
    for s in suggestions:
        if s is None:
            continue
        s.engine = engine
        out.append(s)
    return out


class Engine(ABC):
    """Base class for the three v2 engines."""

    #: Stable engine name, also the value stamped on each Suggestion.engine.
    name: str = "engine"

    @abstractmethod
    def propose(self, ctx: TradeContext) -> list[Suggestion]:
        """Produce this engine's candidate suggestions for a context.

        Every returned Suggestion MUST carry ``engine == self.name`` (use
        :func:`tag_engine`). May be empty.
        """

    def current_risk(self, items: Iterable[Suggestion]) -> float:
        """Modeled risk contribution: summed defined max-loss of THIS engine's
        items. Items belonging to other engines are ignored. Always >= 0."""

        total = 0.0
        for s in items:
            if getattr(s, "engine", None) != self.name:
                continue
            total += abs(float(s.max_loss or 0.0))
        return total

    #: ``risk_contribution`` reads more naturally at call sites; same behaviour.
    def risk_contribution(self, items: Iterable[Suggestion]) -> float:
        return self.current_risk(items)

    @abstractmethod
    def target_allocation(self, engines_cfg: EnginesConfig) -> float:
        """Capital allocation fraction for this engine (from engines.yaml)."""
