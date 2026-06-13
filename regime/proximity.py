"""Earnings proximity tagging for candidate structures.

Tags a structure's expiry set against the next confirmed earnings date:
  PRE        whole structure expires BEFORE the print (no event exposure)
  STRADDLES  entered before the print, an expiry on/after it -> held THROUGH it
  POST       the relevant earnings has already passed (no forward exposure)
  NONE       no known/confirmed earnings date

Doctrine: STRADDLES is invalid for ALL families in v1 (no EVENT family). Guards
and the ranker reject any candidate tagged STRADDLES.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional


class ExpiryEarningsTag(str, Enum):
    PRE = "PRE"
    STRADDLES = "STRADDLES"
    POST = "POST"
    NONE = "NONE"


def tag_structure_vs_earnings(
    expiries: list[date],
    earnings: Optional[date],
    asof: date,
) -> ExpiryEarningsTag:
    """Tag a (possibly multi-expiry) structure against the earnings date."""

    if earnings is None or not expiries:
        return ExpiryEarningsTag.NONE
    if asof > earnings:
        return ExpiryEarningsTag.POST  # the event already passed
    if max(expiries) < earnings:
        return ExpiryEarningsTag.PRE  # entire structure expires before the print
    return ExpiryEarningsTag.STRADDLES  # entered pre-event, held through it


def tag_expiry_vs_earnings(
    expiry: date,
    earnings: Optional[date],
    asof: date,
) -> ExpiryEarningsTag:
    return tag_structure_vs_earnings([expiry], earnings, asof)


def straddles_earnings(expiries: list[date], earnings: Optional[date], asof: date) -> bool:
    """True if the structure would be held through a confirmed earnings print."""

    return tag_structure_vs_earnings(expiries, earnings, asof) is ExpiryEarningsTag.STRADDLES
