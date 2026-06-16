# Keystone v2 — Design Doc (Leverage + Governor)

Delta on v1 (the completed repo). Additive, not a rewrite. v1 is the income
engine; v2 adds a leveraged protected core, a load-bearing trend/convexity
overlay, and the portfolio governor that makes leverage survivable.

## 0. Posture (DD-hard) and honest expectations

- **20% max drawdown is the BINDING constraint.** 20% CAGR is the *potential*
  in good regimes; **mid-to-high-teens is the honest expected** over a full
  cycle. Target Calmar ~1.0 sits at the elite edge.
- The governor *aims* to cap drawdown near 20% but **cannot act inside an
  overnight/limit-down gap** — a genuine tail (2008/2020) can print 25-35%
  before de-levering completes. "~20% typical, deeper in a true tail" is the
  truth. Do not size on the assumption the cap is hard.
- The lever to reach 20% is NOT more leverage or more premium. It is
  **diversification + crisis hedging that bounds drawdown, then leverage
  sized to the bounded drawdown.** Hedging buys leverage headroom.

## 1. Three-engine architecture

| Engine | Return source | Accounts | Touch | Role |
|---|---|---|---|---|
| 1 Income | VRP / theta (defined-risk premium + wheel) | 3 margin + SMSF | weekly + alerts | yield, run at higher heat |
| 2 Core | equity risk premium, levered + protected | margin (LEAPS/PMCC + hedge); SMSF (fully-paid LEAPS/PMCC + protective puts) | monthly+ | the real CAGR driver |
| 3 Overlay | convexity + trend/managed-futures crisis alpha | margin + SMSF, option-expressed | monthly + signal | load-bearing hedge headroom |

Engine 1 = existing v1 strategies, heat raised under governor control.
Engines 2-3 + the governor are new.

## 2. Engine 2 - leveraged protected core

`strategies/leveraged_core.py`
- Capital-efficient long beta via deep-ITM LEAPS (~70-80 delta, 6-12mo) or
  PMCC on quality broad/sector ETFs + quality names. Target effective core
  exposure 1.3-1.7x NLV-allocated capital.
- Margin accounts: LEAPS/PMCC (BPR-efficient).
- SMSF: identical LEAPS/PMCC but **fully paid (no borrowing)** -> compliant
  in the cash account; the diagonal is already permitted (American style).
  Verify derivative provisions with Sudesh + the trust deed; mechanically
  allowed, and it is not borrowing.

`strategies/core_hedge.py` - the STANDING tail hedge (always on, regime-scaled)
- Layered:
  - base layer: OTM index put spreads (SPY/QQQ), rolled - cheap, always on,
    caps the everyday drawdown.
  - tail layer: thin deep-OTM long puts / VIX-style calls - the real crash
    convexity, small premium, large payoff in a gap.
- Sized so the core's modeled severe-tail loss is capped near the DD budget.
- Regime-scaled: increase hedge weight when market regime degrades
  (DEFENSIVE) toward HARD_SKIP. Engine 3's positive crisis alpha lets this
  explicit hedge run lighter than a naked levered-beta book would need.
- SMSF: protective puts / collars on the LEAPS core (no index-spread shorting
  constraints since these are long puts / defined spreads).

## 3. Engine 3 - convexity + trend/managed-futures overlay

`strategies/trend_overlay.py`
- Systematic time-series momentum across a diversified ETF basket: equity
  indices (SPY/QQQ/IWM), bonds (TLT), gold (GLD), energy (XLE/USO), broad
  commodity (DBC), USD (UUP). Signal e.g. 12-1m return sign or 50/200 MA
  state.
- **Expressed only via long-premium DEFINED-RISK options** so it needs no
  stock shorting and works in margin AND SMSF: long trend -> call debit
  spread / LEAP; short trend -> put debit spread. Both directions, no short
  stock.
- Sized **load-bearing** (larger than a return-maximizer would) - this is the
  Calmar improver with documented positive crisis alpha (2008/2022-type
  bears).
- Existing v1 `trend_long` convexity folds in here.

## 4. The Governor - the new spine above portfolio

`governor/portfolio_vol.py` - portfolio vol estimate (realized 20-60d blended
with implied: VIX complex + per-position vega) + cross-engine correlation
matrix (the diversification benefit is measured, not assumed).

`governor/vol_target.py` - target portfolio vol (default 13% annualized).
scale = sigma_target / sigma_now, capped at leverage_max, floored at min.
Vol doubles -> exposure halves. More size when calm, cut on spikes.

`governor/drawdown_governor.py` - high-water-mark tracking; tiered de-lever:
- DD < 10%: full allowed exposure
- 10-15%: scale exposure down (linear to ~50%)
- 15-20%: hedge-heavy, minimum new risk, de-lever Engines 1-2
- >= 20%: defensive - close/hedge, no risk-on until a recovery margin is
  regained (anti-whipsaw re-entry rule)
Applied per-pool AND aggregate. Honest: reduces, does not eliminate,
gap-through risk.

`governor/leverage_allocator.py` - stress-constrained sizing. Increase Engine
1/2 leverage until the modeled severe-tail loss (INCLUDING hedges + Engine 3
crisis alpha) hits the 20% DD budget. That is the leverage the hedge affords.
The hedge has negative marginal risk contribution -> frees budget for Engines
1-2. This is "hedging buys leverage headroom" made concrete.

## 5. Risk budgets and config deltas

`config/risk.yaml` (upgrade) + `config/engines.yaml` (new):
- Engine 1 heat: aggregate defined short-premium max-loss 6% -> 15-18% NLV
  (governor-controlled, not static).
- Engine 2: effective core exposure 1.3-1.7x; hedge sized to cap core
  severe-tail loss near budget.
- Engine 3: trend overlay risk allocation set load-bearing (target it offsets
  a meaningful fraction of Engine 1-2 loss in the severe-tail scenario).
- Portfolio vol target ~13% annualized.
- Governor thresholds 10/15/20% DD; re-entry recovery margin.
- Leverage cap: risk-based (stress-loss / vol budget) is primary; a gross-
  notional ceiling (~2.0-2.5x) as a hard backstop.

## 6. Stress upgrade

`portfolio/stress.py` (upgrade): model the WHOLE leveraged book including
hedges and Engine 3 in each scenario.
- Standard: -5% spot / IV+10 / 2d (beta-mapped) + worst-single-name.
- **Severe tail (new): -20% spot / IV+30 / overnight gap.** Assert the hedge +
  overlay cap aggregate loss near the 20% DD budget; if not, the allocator
  must cut leverage until it does. This is the gate that enforces DD-hard.

## 7. Validation BEFORE live leverage (mandatory gate)

`validation/scenario_replay.py` (new): the system still has no backtester, and
flying blind at leverage is far more dangerous than at single-digit returns.
- Replay historical vol regimes (2008 / 2018-Vol / 2020 / 2022 proxies) and a
  Monte Carlo against governor + engine P&L proxies.
- Report: drawdown distribution vs the 20% budget, leverage utilization path,
  CAGR proxy, governor de-lever events, hedge payoff in tails.
- **Run this and inspect before enabling live leverage.** If the replayed DD
  distribution breaches 20% materially, the leverage cap is too high - lower
  it. This is not optional for a 20%-target leveraged book.

## 8. Reused vs new vs modified (on the existing repo)

- Reused unchanged: universe, events, regime (surface/vol/skew/market),
  ranker spine, execution (whatIf transmit=False), alerts, store, UI shell.
- New: engines/ (orchestration), strategies/leveraged_core.py, core_hedge.py,
  trend_overlay.py, the whole governor/ package, validation/.
- Modified: portfolio/stress.py (severe-tail + full leveraged book),
  ranker (per-engine candidates), config (risk.yaml upgrade, engines.yaml),
  UI (engine + governor panels), alerts (governor-state + de-lever alerts).

## 9. Honest expectations (the iron law)

Target CAGR and tolerable drawdown are one dial. This stack has genuine 20%
*potential* and ~mid-to-high-teens *expected* over a cycle, with ~20% typical
drawdown and deeper tail risk no governor removes. At leverage the system is
**less forgiving of inattention** - acting on CRITICAL alerts is mandatory,
not optional. Validate (SS7) before live leverage. Not financial advice.

## 10. Doctrine additions (to v1 doctrine)

Hedge-and-diversification-first sizing (hedge buys leverage) * vol-target the
whole book, never static leverage * tiered drawdown governor with anti-
whipsaw re-entry * Engine 3 is load-bearing, not optional drag * severe-tail
stress must clear the 20% DD budget or the allocator cuts leverage * never
reach for return via naked/ATM premium (Door B) * validate historically
before enabling live leverage.
