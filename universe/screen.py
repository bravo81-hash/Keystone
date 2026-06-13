"""Weekly liquidity screen -> universe/screened.json.

Run on the slow (weekly) clock against cached Friday chains. Each seed ticker is
reduced to a :class:`TickerSnapshot` (ATM spreads front/back, the leading weekly
expiries, last price, option ADV and near-ATM OI) and run through the hard gates
below. Output is one record per ticker: ``{passed, reasons[], tier, sector,
flags, generated_at}``. Consumers treat a screened.json older than
``screened_max_age_days`` (default 7) as empty and log a warning.

The snapshot-building step reuses ib_client's cached Friday chains and the 2-pass
ATM + 25-delta fetch (no new request pattern); it is injected into
:func:`weekly_screen` so the gate logic stays pure and fully testable offline.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Mapping, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from config.schema import UniverseConfig
from events.earnings import get_next_earnings
from universe.seed import SEED, SeedEntry

logger = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
SCREENED_PATH = Path(__file__).resolve().parent / "screened.json"

EarningsLookup = Callable[[str], object]  # (ticker) -> Event | None


class TickerSnapshot(BaseModel):
    """The market inputs the screen needs for one ticker (from cached chains)."""

    ticker: str
    last_price: float
    atm_bid_front: float
    atm_ask_front: float
    atm_bid_back: float
    atm_ask_back: float
    weekly_expiries: list[date] = Field(default_factory=list)  # sorted, front-first
    option_adv: float = 0.0  # contracts/day
    open_interest_atm: int = 0  # OI near ATM


class ScreenResult(BaseModel):
    ticker: str
    passed: bool
    reasons: list[str] = Field(default_factory=list)  # gate failures (empty if passed)
    tier: str
    sector: str
    flags: dict[str, bool] = Field(default_factory=dict)
    generated_at: str = ""


# --------------------------------------------------------------------------- #
# Gate helpers
# --------------------------------------------------------------------------- #
def relative_spread(bid: float, ask: float) -> Optional[float]:
    """(ask-bid)/mid, or None if there is no two-sided market."""

    mid = (bid + ask) / 2.0
    if mid <= 0 or ask < bid:
        return None
    return (ask - bid) / mid


def count_leading_consecutive_weeklies(expiries: list[date]) -> int:
    """How many expiries from the front are consecutive weeklies (~7 days apart)."""

    if not expiries:
        return 0
    exp = sorted(expiries)
    count = 1
    for prev, cur in zip(exp, exp[1:]):
        gap = (cur - prev).days
        if 6 <= gap <= 8:  # allow holiday drift
            count += 1
        else:
            break
    return count


def is_csp_affordable_smsf(price: float, is_etf: bool, cfg: UniverseConfig) -> bool:
    """100*price within the SMSF per-name budget (12% single / 25% ETF of NLV)."""

    pct = cfg.smsf_affordability_etf_pct if is_etf else cfg.smsf_affordability_single_pct
    return (100.0 * price) <= (pct / 100.0) * cfg.smsf_nlv


# --------------------------------------------------------------------------- #
# Per-ticker screen
# --------------------------------------------------------------------------- #
def screen_ticker(
    entry: SeedEntry,
    snapshot: TickerSnapshot,
    cfg: UniverseConfig,
    *,
    get_earnings: EarningsLookup = get_next_earnings,
    asof: Optional[date] = None,
    generated_at: str = "",
) -> ScreenResult:
    """Apply the hard gates to one ticker. ``passed`` is True iff no reasons."""

    asof = asof or datetime.now(NY).date()
    gates = cfg.gates
    reasons: list[str] = []

    # 1. last price floor
    if snapshot.last_price < gates.min_last_price:
        reasons.append(f"last price {snapshot.last_price:.2f} < {gates.min_last_price:.0f}")

    # 2. ATM spread, front + back
    front = relative_spread(snapshot.atm_bid_front, snapshot.atm_ask_front)
    if front is None:
        reasons.append("no two-sided ATM market (front)")
    elif front > gates.max_atm_spread_front:
        reasons.append(
            f"front ATM spread {front:.1%} > {gates.max_atm_spread_front:.0%}"
        )
    back = relative_spread(snapshot.atm_bid_back, snapshot.atm_ask_back)
    if back is None:
        reasons.append("no two-sided ATM market (back)")
    elif back > gates.max_atm_spread_back:
        reasons.append(f"back ATM spread {back:.1%} > {gates.max_atm_spread_back:.0%}")

    # 3. front consecutive weekly expiries
    weeklies = count_leading_consecutive_weeklies(snapshot.weekly_expiries)
    if weeklies < gates.min_consecutive_weeklies:
        reasons.append(
            f"only {weeklies} consecutive weeklies < {gates.min_consecutive_weeklies}"
        )

    # 4. option ADV + near-ATM OI
    if snapshot.option_adv < gates.min_option_adv:
        reasons.append(f"option ADV {snapshot.option_adv:.0f} < {gates.min_option_adv}")
    if snapshot.open_interest_atm < gates.min_open_interest:
        reasons.append(f"ATM OI {snapshot.open_interest_atm} < {gates.min_open_interest}")

    # 5. earnings known + confirmed (names only; ETFs exempt)
    if not entry.is_etf:
        event = get_earnings(entry.ticker)
        confirmed = bool(event is not None and getattr(event, "confirmed", False))
        if not confirmed:
            reasons.append("earnings unknown or unconfirmed")

    # affordability flags (informational, not a gate)
    flags = {
        "is_etf": entry.is_etf,
        "csp_eligible_smsf": is_csp_affordable_smsf(snapshot.last_price, entry.is_etf, cfg),
    }

    return ScreenResult(
        ticker=entry.ticker,
        passed=not reasons,
        reasons=reasons,
        tier=entry.tier,
        sector=entry.sector,
        flags=flags,
        generated_at=generated_at,
    )


# --------------------------------------------------------------------------- #
# Run / persist / load
# --------------------------------------------------------------------------- #
def run_screen(
    snapshots: Mapping[str, TickerSnapshot],
    cfg: UniverseConfig,
    *,
    seed: tuple[SeedEntry, ...] = SEED,
    get_earnings: EarningsLookup = get_next_earnings,
    asof: Optional[date] = None,
    generated_at: Optional[str] = None,
) -> dict:
    """Screen every seed ticker that has a snapshot. Returns a report dict.

    Tickers without a snapshot are skipped (no data this run). The report is
    ``{"generated_at": iso, "entries": {ticker: ScreenResult-as-dict}}``.
    """

    gen = generated_at or datetime.now(NY).isoformat()
    entries: dict[str, dict] = {}
    for entry in seed:
        snap = snapshots.get(entry.ticker)
        if snap is None:
            continue
        result = screen_ticker(
            entry, snap, cfg, get_earnings=get_earnings, asof=asof, generated_at=gen
        )
        entries[entry.ticker] = result.model_dump(mode="json")
    return {"generated_at": gen, "entries": entries}


def write_screened(report: dict, path: Path = SCREENED_PATH) -> Path:
    Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return Path(path)


def load_screened(
    path: Path = SCREENED_PATH,
    *,
    max_age_days: int = 7,
    asof: Optional[datetime] = None,
) -> dict:
    """Load screened entries, or ``{}`` if the file is missing or stale (>N days).

    Staleness doctrine: a screened.json older than ``max_age_days`` is treated as
    empty (all entries skipped) and a warning is logged — never silently used.
    """

    p = Path(path)
    if not p.exists():
        logger.warning("screened.json not found at %s; treating as empty", p)
        return {}
    report = json.loads(p.read_text(encoding="utf-8"))
    gen_raw = report.get("generated_at")
    if not gen_raw:
        logger.warning("screened.json missing generated_at; treating as empty")
        return {}
    generated = datetime.fromisoformat(gen_raw)
    now = asof or datetime.now(NY)
    age_days = (now - generated).total_seconds() / 86400.0
    if age_days > max_age_days:
        logger.warning(
            "screened.json is %.1f days old (> %d); treating as empty",
            age_days,
            max_age_days,
        )
        return {}
    return report.get("entries", {})


def weekly_screen(
    ib_client,
    build_snapshot: Callable[[SeedEntry, object], Optional[TickerSnapshot]],
    cfg: UniverseConfig,
    *,
    seed: tuple[SeedEntry, ...] = SEED,
    get_earnings: EarningsLookup = get_next_earnings,
    out_path: Path = SCREENED_PATH,
    force: bool = False,
) -> dict:
    """Live weekly job: build snapshots from cached Friday chains, screen, persist.

    ``build_snapshot(entry, ib_client) -> TickerSnapshot | None`` performs the
    2-pass ATM + 25-delta extraction off ib_client's cached chains (injected so
    the gate logic stays testable offline). Honors the Fridays-only chain policy
    unless ``force``.
    """

    if not (force or ib_client.is_chain_refresh_day()):
        logger.warning("weekly_screen called on a non-Friday without force; skipping")
        return {"generated_at": datetime.now(NY).isoformat(), "entries": {}}

    snapshots: dict[str, TickerSnapshot] = {}
    for entry in seed:
        snap = build_snapshot(entry, ib_client)
        if snap is not None:
            snapshots[entry.ticker] = snap

    report = run_screen(snapshots, cfg, seed=seed, get_earnings=get_earnings)
    write_screened(report, out_path)
    return report
