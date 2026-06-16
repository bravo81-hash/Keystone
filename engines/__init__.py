"""Keystone v2 engines — the three return sources behind a uniform interface.

  Engine 1 (income)  — existing v1 defined-risk premium + wheel (this stage).
  Engine 2 (core)    — leveraged protected core: LEAPS/PMCC + standing hedge.
  Engine 3 (overlay) — trend/managed-futures + convexity, defined-risk options.

Each implements :class:`engines.base.Engine` so the ranker (Stage 18) and the
governor (Stage 16) treat them uniformly: ``propose(ctx) -> [Suggestion]`` (each
tagged with the engine name), ``current_risk(items)`` and ``target_allocation``.
This stage scaffolds the interface and wraps Engine 1 with NO behaviour change
to the v1 strategies.
"""

from __future__ import annotations

from engines.base import Engine, tag_engine
from engines.engine1_income import IncomeEngine

__all__ = ["Engine", "tag_engine", "IncomeEngine"]
