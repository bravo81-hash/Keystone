"""Account profiles, mandates, and instrument classification.

An ``AccountProfile`` carries the account's pool (trading | investing), its
structural ``blocked_rules``, and any budget overrides. ``classify(contract)``
maps a contract to its ``InstrumentClass`` — the vocabulary mandates and budgets
speak. The default topology is 3 trading (margin) + 1 investing (SMSF cash); the
SMSF blocks multi-expiry combos on European cash-settled index options.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from config.schema import AccountsConfig
from core.models import Contract, InstrumentClass, SecType


# --------------------------------------------------------------------------- #
# Instrument classification
# --------------------------------------------------------------------------- #
#: European, cash-settled index options. These are the only instruments the SMSF
#: cash account is structurally restricted on (no multi-expiry combos).
EU_CASH_INDEX_TICKERS: frozenset[str] = frozenset({"SPX", "RUT", "NDX", "XSP"})

#: Option-liquid ETFs Keystone may trade. Used to distinguish ETF options from
#: single-name equity options. Extended by the Stage 1 universe seed; kept here
#: so ``classify`` works standalone. (Broad + sector/thematic ETFs.)
DEFAULT_ETF_TICKERS: frozenset[str] = frozenset(
    {
        "SPY", "QQQ", "IWM", "DIA",
        "XLE", "XLF", "XLK", "XLU", "XLI", "XLV", "XLP", "XLY", "XLB", "XLRE",
        "SMH", "XBI", "GDX", "GDXJ", "TLT", "HYG", "EEM", "EWZ", "FXI", "KRE",
    }
)


def classify(
    contract: Contract,
    etf_tickers: frozenset[str] = DEFAULT_ETF_TICKERS,
) -> InstrumentClass:
    """Classify a contract into its settlement/permission ``InstrumentClass``.

    Order of resolution:
      1. EU cash-settled index tickers (SPX/RUT/NDX/XSP) -> EU_CASH_INDEX
      2. futures / future-options (secType FUT or FOP) -> FUT_OPT
      3. known ETF tickers -> US_ETF_OPT
      4. everything else -> US_EQUITY_OPT
    """

    symbol = contract.symbol.upper()
    if symbol in EU_CASH_INDEX_TICKERS:
        return InstrumentClass.EU_CASH_INDEX
    if contract.sec_type in (SecType.FOP, SecType.FUT):
        return InstrumentClass.FUT_OPT
    if symbol in etf_tickers:
        return InstrumentClass.US_ETF_OPT
    return InstrumentClass.US_EQUITY_OPT


# --------------------------------------------------------------------------- #
# Pools, blocked rules, profiles
# --------------------------------------------------------------------------- #
class Pool(str, Enum):
    TRADING = "trading"
    INVESTING = "investing"


@dataclass(frozen=True)
class BlockedRule:
    """A structural restriction.

    Matching: the instrument class must match. ``multi_expiry`` of None matches
    any candidate; True matches only multi-expiry structures (the SMSF EU
    cash-index rule); False matches only single-expiry structures.
    """

    instrument_class: InstrumentClass
    multi_expiry: Optional[bool] = None

    def matches(self, instrument_class: InstrumentClass, multi_expiry: bool) -> bool:
        if self.instrument_class != instrument_class:
            return False
        if self.multi_expiry is None:
            return True
        return self.multi_expiry == multi_expiry


@dataclass
class AccountProfile:
    """One IBKR account's mandate + budget context."""

    account_id: str
    label: str
    pool: Pool
    blocked_rules: list[BlockedRule] = field(default_factory=list)
    budget_overrides: dict = field(default_factory=dict)
    nlv: Optional[float] = None

    def is_blocked(self, instrument_class: InstrumentClass, multi_expiry: bool = False) -> bool:
        """True if any blocked rule forbids this (instrument_class, multi_expiry)."""

        return any(r.matches(instrument_class, multi_expiry) for r in self.blocked_rules)

    def is_trading(self) -> bool:
        return self.pool is Pool.TRADING

    def is_investing(self) -> bool:
        return self.pool is Pool.INVESTING


# --------------------------------------------------------------------------- #
# Topology
# --------------------------------------------------------------------------- #
#: The SMSF's standing structural rule: no multi-expiry combos on EU cash-index.
SMSF_BLOCKED_RULE = BlockedRule(InstrumentClass.EU_CASH_INDEX, multi_expiry=True)


def default_topology() -> list[AccountProfile]:
    """Default 3-trading-margin + 1-SMSF-cash topology (placeholder ids)."""

    return [
        AccountProfile("REPLACE-TRADING-1", "Trading 1 (margin)", Pool.TRADING, nlv=100000.0),
        AccountProfile("REPLACE-TRADING-2", "Trading 2 (margin)", Pool.TRADING, nlv=100000.0),
        AccountProfile("REPLACE-TRADING-3", "Trading 3 (margin)", Pool.TRADING, nlv=100000.0),
        AccountProfile(
            "REPLACE-SMSF",
            "SMSF (cash)",
            Pool.INVESTING,
            blocked_rules=[SMSF_BLOCKED_RULE],
            nlv=92000.0,
        ),
    ]


def list_managed_accounts(ib: object) -> list[dict]:
    """Discover the TWS managed accounts + their NLV (one accountSummary call).

    Returns ``[{"account": id, "nlv": float|None}, ...]``. Used by the UI account
    selector. ``ib`` is a connected ib_insync IB (or MockIB).
    """

    rows = ib.accountSummary()
    accounts: list[dict] = []
    for acct in ib.managedAccounts():
        nlv = next(
            (float(r.value) for r in rows
             if getattr(r, "account", None) == acct and getattr(r, "tag", None) == "NetLiquidation"),
            None,
        )
        accounts.append({"account": acct, "nlv": nlv})
    return accounts


def from_config(accounts_config: AccountsConfig) -> list[AccountProfile]:
    """Build ``AccountProfile`` objects from a loaded ``AccountsConfig``."""

    profiles: list[AccountProfile] = []
    for acct in accounts_config.accounts:
        rules = [
            BlockedRule(InstrumentClass(r.instrument_class), multi_expiry=r.multi_expiry)
            for r in acct.blocked_rules
        ]
        profiles.append(
            AccountProfile(
                account_id=acct.account_id,
                label=acct.label,
                pool=Pool(acct.pool),
                blocked_rules=rules,
                budget_overrides=dict(acct.budget_overrides),
                nlv=acct.nlv,
            )
        )
    return profiles
