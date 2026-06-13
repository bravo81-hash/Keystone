"""Curated seed universe: top-option-volume US names + sector/thematic ETFs.

Not a market-wide scanner — a curated pool screened weekly (pacing). Each entry
carries: ticker, tier ("A" mega-cap/index-like | "B" idiosyncratic), GICS sector
(or theme for broad ETFs), and is_etf. Mega-caps and broad/sector ETFs are
Tier A; the ranker applies a 0.6x multiplier to Tier B (Stage 9).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedEntry:
    ticker: str
    tier: str  # "A" | "B"
    sector: str  # GICS sector, or theme label for broad ETFs
    is_etf: bool = False


# GICS sector labels used below.
IT = "Information Technology"
HC = "Health Care"
FIN = "Financials"
DISC = "Consumer Discretionary"
STPL = "Consumer Staples"
COMM = "Communication Services"
INDU = "Industrials"
ENE = "Energy"
UTIL = "Utilities"
RE = "Real Estate"
MATL = "Materials"

#: Single names (~74). Tier A = mega-cap/index-like; Tier B = idiosyncratic.
_NAMES: tuple[SeedEntry, ...] = (
    SeedEntry("AAPL", "A", IT),
    SeedEntry("MSFT", "A", IT),
    SeedEntry("NVDA", "A", IT),
    SeedEntry("AMZN", "A", DISC),
    SeedEntry("GOOGL", "A", COMM),
    SeedEntry("META", "A", COMM),
    SeedEntry("TSLA", "A", DISC),
    SeedEntry("AMD", "A", IT),
    SeedEntry("AVGO", "A", IT),
    SeedEntry("NFLX", "A", COMM),
    SeedEntry("JPM", "A", FIN),
    SeedEntry("BAC", "A", FIN),
    SeedEntry("GS", "A", FIN),
    SeedEntry("MS", "A", FIN),
    SeedEntry("C", "B", FIN),
    SeedEntry("WFC", "A", FIN),
    SeedEntry("SCHW", "B", FIN),
    SeedEntry("BLK", "A", FIN),
    SeedEntry("V", "A", FIN),
    SeedEntry("MA", "A", FIN),
    SeedEntry("AXP", "B", FIN),
    SeedEntry("XOM", "A", ENE),
    SeedEntry("CVX", "A", ENE),
    SeedEntry("COP", "B", ENE),
    SeedEntry("PFE", "B", HC),
    SeedEntry("LLY", "A", HC),
    SeedEntry("UNH", "A", HC),
    SeedEntry("JNJ", "A", HC),
    SeedEntry("MRK", "A", HC),
    SeedEntry("ABBV", "A", HC),
    SeedEntry("BA", "B", INDU),
    SeedEntry("CAT", "A", INDU),
    SeedEntry("DE", "B", INDU),
    SeedEntry("GE", "B", INDU),
    SeedEntry("RTX", "B", INDU),
    SeedEntry("LMT", "B", INDU),
    SeedEntry("NOC", "B", INDU),
    SeedEntry("COST", "A", STPL),
    SeedEntry("WMT", "A", STPL),
    SeedEntry("HD", "A", DISC),
    SeedEntry("MCD", "A", DISC),
    SeedEntry("NKE", "B", DISC),
    SeedEntry("DIS", "A", COMM),
    SeedEntry("SBUX", "B", DISC),
    SeedEntry("KO", "A", STPL),
    SeedEntry("PEP", "A", STPL),
    SeedEntry("MO", "B", STPL),
    SeedEntry("PLTR", "B", IT),
    SeedEntry("COIN", "B", FIN),
    SeedEntry("MU", "B", IT),
    SeedEntry("INTC", "B", IT),
    SeedEntry("CSCO", "B", IT),
    SeedEntry("ORCL", "A", IT),
    SeedEntry("CRM", "A", IT),
    SeedEntry("ADBE", "A", IT),
    SeedEntry("QCOM", "B", IT),
    SeedEntry("TXN", "B", IT),
    SeedEntry("PYPL", "B", FIN),
    SeedEntry("UBER", "B", INDU),
    SeedEntry("ABNB", "B", DISC),
    SeedEntry("SHOP", "B", IT),
    SeedEntry("SNOW", "B", IT),
    SeedEntry("PANW", "B", IT),
    SeedEntry("CRWD", "B", IT),
    SeedEntry("NET", "B", IT),
    SeedEntry("DKNG", "B", DISC),
    SeedEntry("F", "B", DISC),
    SeedEntry("GM", "B", DISC),
    SeedEntry("SOFI", "B", FIN),
    SeedEntry("HOOD", "B", FIN),
    SeedEntry("T", "A", COMM),
    SeedEntry("VZ", "A", COMM),
    SeedEntry("FDX", "B", INDU),
    SeedEntry("UPS", "B", INDU),
)

#: Sector / thematic ETFs (21). All Tier A (broad/sector). Theme used as sector.
_ETFS: tuple[SeedEntry, ...] = (
    SeedEntry("XLE", "A", ENE, is_etf=True),
    SeedEntry("XLF", "A", FIN, is_etf=True),
    SeedEntry("XLK", "A", IT, is_etf=True),
    SeedEntry("XLU", "A", UTIL, is_etf=True),
    SeedEntry("XLI", "A", INDU, is_etf=True),
    SeedEntry("XLV", "A", HC, is_etf=True),
    SeedEntry("XLP", "A", STPL, is_etf=True),
    SeedEntry("XLY", "A", DISC, is_etf=True),
    SeedEntry("XLB", "A", MATL, is_etf=True),
    SeedEntry("XLRE", "A", RE, is_etf=True),
    SeedEntry("SMH", "A", IT, is_etf=True),  # semiconductors
    SeedEntry("XBI", "A", HC, is_etf=True),  # biotech
    SeedEntry("GDX", "A", MATL, is_etf=True),  # gold miners
    SeedEntry("GDXJ", "A", MATL, is_etf=True),  # junior gold miners
    SeedEntry("TLT", "A", "Fixed Income", is_etf=True),
    SeedEntry("HYG", "A", "Fixed Income", is_etf=True),
    SeedEntry("EEM", "A", "Emerging Markets", is_etf=True),
    SeedEntry("EWZ", "A", "Brazil", is_etf=True),
    SeedEntry("FXI", "A", "China", is_etf=True),
    SeedEntry("KRE", "A", FIN, is_etf=True),  # regional banks
    SeedEntry("IWM", "A", "Broad Market", is_etf=True),
)

#: The full seed pool.
SEED: tuple[SeedEntry, ...] = _NAMES + _ETFS

_BY_TICKER: dict[str, SeedEntry] = {e.ticker: e for e in SEED}


def get_seed() -> tuple[SeedEntry, ...]:
    """Return the full seed pool."""

    return SEED


def seed_tickers() -> list[str]:
    return [e.ticker for e in SEED]


def by_ticker(ticker: str) -> SeedEntry | None:
    return _BY_TICKER.get(ticker.upper())


def names() -> list[SeedEntry]:
    return [e for e in SEED if not e.is_etf]


def etfs() -> list[SeedEntry]:
    return [e for e in SEED if e.is_etf]
