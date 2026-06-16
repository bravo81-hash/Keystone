"""Portfolio stress: a beta-mapped market row + a worst-single-name row.

Market row: -5% spot / IV+10 / 2d, beta-mapped per name (60d beta vs SPY).
Worst-name row: the single name with the worst idiosyncratic shock — -15% gap /
IV+15, or +/-1.5x the implied move if the name is inside an earnings window.

Each position's loss is floored at its defined max-loss (you can't lose more
than a defined-risk structure's max loss). Losses are compared to a stress
ceiling calibrated to THIS book's expected weekly/monthly P&L (configurable).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config.schema import StressCfg

MARKET_SPOT_SHOCK = -0.05
MARKET_IV_SHOCK = 10.0  # vol points
WORST_NAME_GAP = -0.15
WORST_NAME_IV_SHOCK = 15.0  # vol points
SEVERE_SPOT_SHOCK = -0.20  # v2 severe tail: -20% overnight gap
SEVERE_IV_SHOCK = 30.0  # IV +30 (vol points)


@dataclass
class StressPosition:
    """A position expressed for stress: dollar greeks + defined max-loss floor.

    v2: ``severe_payoff`` lets an option structure (Engine 2 hedge, Engine 3
    overlay) supply its MODELED severe-tail P&L directly — the greek
    linearization is poor for deep-OTM convexity over a -20% gap, so the engines'
    intrinsic-based payoff is used for the severe row when provided.
    """

    symbol: str
    spot: float
    beta: float = 1.0
    delta_shares: float = 0.0  # net delta * multiplier * contracts (share-equivalent)
    gamma_shares: float = 0.0  # net gamma * multiplier * contracts
    vega_dollars_per_volpt: float = 0.0  # P&L per +1 vol point
    max_loss: Optional[float] = None  # defined-risk floor (positive number)
    earnings_window: bool = False
    implied_move: float = 0.0  # fractional 1-sigma implied move (earnings)
    severe_payoff: Optional[float] = None  # modeled severe-tail P&L override ($, signed)
    engine: Optional[str] = None  # "income" | "core" | "overlay" (for attribution)

    def pnl(self, spot_move_frac: float, iv_shock_volpts: float) -> float:
        price_change = self.spot * spot_move_frac
        pnl = self.delta_shares * price_change + 0.5 * self.gamma_shares * price_change**2
        pnl += self.vega_dollars_per_volpt * iv_shock_volpts
        if self.max_loss is not None:
            pnl = max(pnl, -abs(self.max_loss))  # cannot lose more than defined risk
        return pnl

    def pnl_severe(self, spot_move_frac: float, iv_shock_volpts: float) -> float:
        """Severe-tail P&L: the modeled override when set, else the greek pnl."""

        if self.severe_payoff is not None:
            return self.severe_payoff
        return self.pnl(spot_move_frac, iv_shock_volpts)

    def scaled(self, factor: float) -> "StressPosition":
        """A copy with all dollar quantities scaled (used to size leverage down)."""

        return StressPosition(
            symbol=self.symbol, spot=self.spot, beta=self.beta,
            delta_shares=self.delta_shares * factor, gamma_shares=self.gamma_shares * factor,
            vega_dollars_per_volpt=self.vega_dollars_per_volpt * factor,
            max_loss=None if self.max_loss is None else self.max_loss * factor,
            earnings_window=self.earnings_window, implied_move=self.implied_move,
            severe_payoff=None if self.severe_payoff is None else self.severe_payoff * factor,
            engine=self.engine,
        )


@dataclass
class StressResult:
    market_pnl: float
    worst_name: Optional[str]
    worst_name_pnl: float
    ceiling: Optional[float]
    market_within_ceiling: bool
    worst_within_ceiling: bool


@dataclass
class SevereTailResult:
    """The -20% / IV+30 overnight-gap scenario over the FULL leveraged book.

    The DD-hard gate: ``aggregate_loss`` must be <= the DD budget, else the
    leverage allocator must cut size. ``implied_max_leverage`` is the multiple of
    the current book that would bring the loss exactly to the budget (>= 1 means
    in-budget at current size; < 1 means cut to that fraction)."""

    aggregate_pnl: float  # signed (negative = loss)
    aggregate_loss: float  # positive loss magnitude (0 when the book gains)
    dd_budget: float
    within_budget: bool
    implied_max_leverage: float
    hedge_offset: float  # summed positive severe payoff from hedge/overlay legs


def beta_60d(name_closes: list[float], spy_closes: list[float], window: int = 60) -> float:
    """60-day return beta of a name vs SPY. Returns 1.0 if undeterminable."""

    n = min(len(name_closes), len(spy_closes))
    if n < window + 1:
        if n < 2:
            return 1.0
        window = n - 1
    nm = name_closes[-(window + 1):]
    sp = spy_closes[-(window + 1):]
    name_rets = [nm[i] / nm[i - 1] - 1 for i in range(1, len(nm))]
    spy_rets = [sp[i] / sp[i - 1] - 1 for i in range(1, len(sp))]
    mean_s = sum(spy_rets) / len(spy_rets)
    var_s = sum((r - mean_s) ** 2 for r in spy_rets)
    if var_s == 0:
        return 1.0
    mean_n = sum(name_rets) / len(name_rets)
    cov = sum((name_rets[i] - mean_n) * (spy_rets[i] - mean_s) for i in range(len(spy_rets)))
    return cov / var_s


def market_row_pnl(
    book: list[StressPosition],
    *,
    spot_shock: float = MARKET_SPOT_SHOCK,
    iv_shock: float = MARKET_IV_SHOCK,
) -> float:
    """Full-book P&L under the beta-mapped market scenario."""

    total = 0.0
    for pos in book:
        name_move = pos.beta * spot_shock  # beta-mapped
        total += pos.pnl(name_move, iv_shock)
    return total


def worst_single_name(
    book: list[StressPosition],
    *,
    gap: float = WORST_NAME_GAP,
    iv_shock: float = WORST_NAME_IV_SHOCK,
    earnings_move_mult: float = 1.5,
) -> tuple[Optional[str], float]:
    """Worst idiosyncratic single-name shock across the book."""

    worst_sym: Optional[str] = None
    worst_pnl = 0.0
    for pos in book:
        if pos.earnings_window and pos.implied_move > 0:
            move = earnings_move_mult * pos.implied_move
        else:
            move = abs(gap)
        # take the worse of a down-gap and up-gap
        pnl = min(pos.pnl(-move, iv_shock), pos.pnl(move, iv_shock))
        if worst_sym is None or pnl < worst_pnl:
            worst_sym, worst_pnl = pos.symbol, pnl
    return worst_sym, worst_pnl


def severe_tail_row(
    book: list[StressPosition],
    *,
    spot_shock: float = SEVERE_SPOT_SHOCK,
    iv_shock: float = SEVERE_IV_SHOCK,
) -> float:
    """Full-book P&L in the severe-tail gap (beta-mapped), using modeled severe
    payoffs for the hedge/overlay legs that supply them."""

    total = 0.0
    for pos in book:
        total += pos.pnl_severe(pos.beta * spot_shock, iv_shock)
    return total


def severe_tail_stress(
    book: list[StressPosition],
    dd_budget: float,
    *,
    cfg: Optional[StressCfg] = None,
) -> SevereTailResult:
    """Run the severe-tail scenario over the full leveraged book and gate it
    against the DD budget. Feeds the governor + the leverage allocator."""

    cfg = cfg or StressCfg()
    pnl = severe_tail_row(book, spot_shock=cfg.severe_spot_shock, iv_shock=cfg.severe_iv_shock)
    loss = max(0.0, -pnl)
    budget = abs(dd_budget)
    within = loss <= budget + 1e-6
    implied = float("inf") if loss <= 0 else budget / loss
    hedge_offset = sum(
        p.severe_payoff for p in book
        if p.severe_payoff is not None and p.severe_payoff > 0
    )
    return SevereTailResult(pnl, loss, budget, within, implied, hedge_offset)


def stress_book(book: list[StressPosition], cfg: Optional[StressCfg] = None) -> StressResult:
    """Run both stress rows and compare to the configured ceiling."""

    cfg = cfg or StressCfg()
    market = market_row_pnl(book, spot_shock=cfg.market_spot_shock, iv_shock=cfg.market_iv_shock)
    worst_sym, worst = worst_single_name(
        book,
        gap=cfg.worst_name_gap,
        iv_shock=cfg.worst_name_iv_shock,
        earnings_move_mult=cfg.earnings_implied_move_mult,
    )
    ceiling = cfg.weekly_pnl_ceiling
    if ceiling is None:
        return StressResult(market, worst_sym, worst, None, True, True)
    return StressResult(
        market_pnl=market,
        worst_name=worst_sym,
        worst_name_pnl=worst,
        ceiling=ceiling,
        market_within_ceiling=market >= -abs(ceiling),
        worst_within_ceiling=worst >= -abs(ceiling),
    )
