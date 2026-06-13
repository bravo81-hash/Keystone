# Keystone — Design Doc v1.0

Low-touch stock/ETF trading + investing system. Separate app, separate repo
(`keystone`). Complements the index book (Forward-Vol-Scanner) — does NOT
share code or process. Engineering patterns re-implemented, not imported.

Anchored to America/New_York. IBKR TWS execution/data. OptionStrat
out-of-hours modelling. transmit=False on every staged order, always.

---

## 0. Mandate & account topology

| Pool | Accounts | Mandate | Slow clock | Notes |
|---|---|---|---|---|
| Trading | 3 margin | defined-risk short premium + small long-premium trend convexity | weekly checkpoint | longer-DTE, broader underlyings than index book |
| Investing + Wheel | SMSF (cash, ~AUD 140k / ~USD 92k) | accumulate quality via wheel, hold protected core | monthly/quarterly rebalance; weekly-fortnightly wheel mgmt | assignment-tolerant; no European cash-index multi-expiry |

SMSF permission ground truth (verified 2026-06): cash account permanently,
no margin/short/debit. Restriction is settlement style, not strategy family:
multi-expiry combos blocked on European cash-settled index options
(SPX/RUT/NDX/XSP); American-style (stocks, SPY/QQQ/IWM, ES) unrestricted.
whatIf is the final arbiter; rejects logged to a learn-table.

---

## 1. Architecture — the two-clock spine

The system is low-touch-but-responsive via two independent clocks.

**Slow clock (scheduled, you drive it).**
- Trading: one fixed weekly checkpoint day. New entries + roll decisions.
- Investing: monthly/quarterly rebalance to target weights.
- Universe screen runs here (pacing-heavy, weekly).

**Fast clock (alert-only, automated, pacing-light — pings you on exceptions).**
- Marks open positions + key greeks EOD (optional 3x intraday). Small
  position count => cheap, well inside TWS budgets.
- Emits alerts; you act within days ONLY when one fires. You never sit
  watching. UI panel delivery (v1); store designed so push/email can be
  added later without rework.

Module layout:
```
keystone/
  config/            accounts.yaml, universe.yaml, investing.yaml, risk.yaml
  core/              ib_client (pacing), models, bs_pricing, context
  universe/          seed, screen -> screened.json
  events/            base, earnings (IBKR/Finnhub/CSV), dividends,
                     earnings_premium
  regime/            market_regime (VIX-complex + trend), stock_regime,
                     blend + hard-skip veto
  strategies/        credit_spread, iron_condor, trend_long (LEAPS/diagonal),
                     wheel_csp, wheel_cc, collar, pmcc(opt)
                     uniform propose(ctx) -> Suggestion
  selection/         ranker (mandate filter -> per-sleeve candidates -> cards)
  portfolio/         pools, budgets, stress (beta-mapped + worst-name), fit
  alerts/            monitor, triggers, severity, alert_store
  execution/         n_leg_combo, whatif (transmit=False), mid_walk_in,
                     optionstrat_links
  store/             sqlite audit (positions, entries+rationale, alerts,
                     screen snapshots, whatif, edge audit)
  ui/                Flask + browser panels
```

Reused-as-pattern (re-implemented fresh): pacing ib_client (batch-40-and-
cancel, TTL caches, Fridays-only chains), whatIf N-leg transmit=False,
sqlite audit, BS risk graphs, Flask shell.

---

## 2. Universe & screens

Curated seed, screened weekly. Not a market-wide scanner (pacing).

- Seed pool ~80 top-option-volume US names + liquid sector/thematic ETFs;
  per entry: ticker, tier (A mega-cap/index-like | B idiosyncratic),
  sector (GICS), is_etf.
- Hard screens (weekly, cached Friday chains):
  - ATM bid-ask <= 5% mid front, <= 8% back
  - front 4 consecutive weekly expiries listed
  - last price >= $30
  - option ADV >= 5000/day, OI >= 1000 near candidate strikes
  - earnings date KNOWN + confirmed (names); else hard skip for any
    expiry that could straddle it
  - SMSF affordability flags: csp_eligible if 100*price <= 12% SMSF NLV
    (single name) or 25% (is_etf)
- Output `universe/screened.json` {passed, reasons[], tier, sector, flags,
  generated_at}. Stale > 7 days => ranker skips all entries + warns.

---

## 3. Regime gate

Lightweight port of TE Console market regime (you trust it) + per-stock
regime from the chain. Built fresh in this repo.

**Market regime (the on/off gate).** Term structure via VIX9D/VIX/VIX3M +
trend filter (index vs rising/falling 200DMA). Output a state; HARD-SKIP
states veto ALL new entries in BOTH sleeves. Doctrine: forced cadence never
overrides SKIP. Defensive (non-skip) states trigger collar suggestions on
the SMSF core.

**Per-stock regime (selection + sizing).** From the chain/history only (no
VIX analogue per name): term slope (ATM IV 9d/30d/90d interpolated via
total variance), IVR/IVP (1yr OPTION_IMPLIED_VOLATILITY history), VRP
(IV30 - RV20), 25D risk-reversal skew (sanity flags on extremes).

**Blend.** Stock entry score = 0.4 * market + 0.6 * stock. Market hard-skip
vetoes regardless of stock score.

---

## 4. Events — earnings + dividends

- `events/base.py`: Event(symbol, date, kind {EARNINGS, DIV}, confirmed,
  meta). get_events(symbol, window), get_next_earnings(symbol),
  get_next_exdiv(symbol).
- Earnings source priority: IBKR fundamentals (reqFundamentalData) ->
  Finnhub (FINNHUB_KEY env) -> manual CSV override (wins when present).
  Unconfirmed/missing => confirmed=False => hard skip for straddling
  expiries.
- Implied earnings move: front-expiry ATM straddle vs total-variance
  baseline excluding the event. Realized: last 8 quarters |close->open|,
  median. (Used only if an EVENT family is ever added — deferred; see SS12.)
- Dividends: ex-div date + amount via generic tick 456, TTL-cached. Feeds
  assignment-risk checks (short call ITM, extrinsic < dividend) and CC/wheel
  skip windows.

---

## 5. Strategy families

All modules: `propose(ctx) -> Suggestion`, declare instrument-class validity,
run `american_guards(ctx)` (no short leg straddling confirmed earnings except
a deliberate event family; ex-div assignment-risk block; pin-risk note at
<=2 DTE). Earnings-excluded by default; ETFs exempt from the earnings binary.

### TRADING SLEEVE — 3 margin accounts. Weekly checkpoint + alerts.

**A. Defined-risk short premium (workhorse).**
- Structures: put credit spread (bullish/neutral), call credit spread
  (bearish/neutral), iron condor (range/neutral).
- Underlyings: liquid ETFs preferred (no earnings binary) + quality
  mega-caps (earnings-excluded).
- Entry: 30-60 DTE (target ~45). Short strike ~16-30D (default 20D).
  Width sized so defined max-loss fits per-position budget. Per-stock IVR
  floor >= 30 (sell only when premium rich; thin credit doesn't justify gap
  risk). Selection bias: put spreads in benign/uptrend + decent IVR;
  condors range-bound + elevated IVR; call spreads overbought/downtrend.
- Management (all alert-driven): profit target 50% max -> close; stop
  loss = 2x credit -> close; must-touch-by 21 DTE -> checkpoint decision
  (roll out or close); short strike tested -> alert (defend/close).

**B. Long-premium trend convexity (diversifier, small).**
- Rationale: the convexity the all-short-vol book lacks; pays when
  short-vol bleeds (trending/volatile tape). Long vega + long delta.
- Structures: LEAPS (deep ITM ~70-80D, 6-12mo) stock-replacement;
  diagonal (long LEAPS + short ~30D monthly call) for directional carry;
  or long vertical debit spread 60-120 DTE.
- Trend filter: underlying above rising 200DMA + positive momentum (calls);
  below falling 200DMA (puts).
- Entry: trend confirmed, on checkpoint. Defined risk = debit. Size small:
  <= 0.5% NLV per position; aggregate trend sleeve <= a few % NLV.
- Management (low-touch by design — let it run): trail underlying stop
  (close if trend invalidated, e.g. breaks back through 200DMA) -> alert;
  diagonal short call rolled monthly at checkpoint or 80% profit; no PT on
  the long leg (let trends run); optional partial scale-out.

### SMSF — investing + wheel. Monthly+ core, weekly-fortnightly wheel, alerts.

**C. Wheel (accumulation engine).**
- CSP leg: cash-secured put on quality you'd own, 30-45 DTE, ~20-30D
  (closer to ATM — assignment desired), strike at/below target acquisition
  price, cash reserved = strike*100. Manage 50% profit -> close & redeploy,
  OR allow assignment if you want the shares. Roll only to avoid assignment
  when you don't yet want the stock.
- On assignment -> shares become core -> switch to CC.
- CC leg: against core shares, 30-45 DTE, ~15-25D (low delta, rarely
  called away), roll at 21 DTE or 80% profit. Skip a cycle if strike would
  straddle earnings or sit in an ex-div assignment-risk window.

**D. Investing core + protection.**
- Core: target-weight list of quality ETFs/names, built primarily via the
  wheel (CSP entries) not market buys. Rebalance monthly/quarterly to
  weights at the slow checkpoint.
- Collar: when market regime degrades (regime -> defensive), suggest collar
  on core (long put ~25D financed by the existing CC). Event-driven,
  near-zero touch; removed when regime normalizes.
- PMCC (default OFF, config toggle; shares the trend_long/diagonal module):
  LEAPS ~70-80D + short ~20-30D monthly call, monthly roll. Capital-
  efficient core-replacement where full capital isn't wanted. (Earlier
  v1.1 call honored — code present, off by default.)

---

## 6. Alert engine (the centerpiece)

Makes the system low-touch-but-responsive. Cheap: monitors OPEN positions
only (small N), not the universe.

- Cadence: EOD mandatory; optional 3x intraday. Cron/scheduled; UI-only
  delivery in v1.
- Per-position computed each run: mark + P&L vs entry; short-leg
  delta/moneyness; DTE; distance underlying->short strike in ATR units;
  assignment-risk flags (ex-div + ITM + extrinsic < div; short put deep
  ITM, extrinsic < $0.05); pin-risk (<=2 DTE, within 0.5*20d ATR);
  earnings-gap detection on exposed names.
- Portfolio-level each run: budget utilization, sector concentration,
  correlation, beta-mapped stress refresh.
- Severity tiers:
  - INFO — profit target hit (opportunistic close / free capital)
  - WARN — approaching stop; must-touch-by DTE reached; short strike within
    X*ATR; roll due
  - CRITICAL — stop breached; short strike breached; assignment imminent;
    market regime flipped to hard-skip; pin risk
- UI alerts queue: severity-sorted; each shows position + trigger +
  suggested action (close/roll/defend/hedge), OptionStrat deep-link, and a
  stage-to-TWS button (whatIf, transmit=False).
- alert_store: every alert + resolution logged (future edge audit).

---

## 7. Portfolio & risk

Two pools, separate budgets.

**Trading (3 margin), per $100k NLV:** defined-risk max-loss per position
<= 1%; aggregate short-premium risk cap; trend sleeve aggregate cap (small,
~a few %); max 6 positions; max 2 names per sector; correlation cap.
Optional read-only ingest of index-book positions (from the other app /
IBKR) to avoid doubling correlated risk — nice-to-have, flagged.

**SMSF buckets:** CSP cash-reserve cap; core-holdings notional cap;
assignment notional per name 12% (single) / 25% (diversified ETF); hedge
(collar) allowance; max 2 names per sector. (Replaces any rigid pool split.)

**Stress:** market scenario -5% spot / IV+10 / 2d, beta-mapped per name
(60d beta vs SPY from cached daily history); PLUS worst-single-name
idiosyncratic -15% gap / IV+15 (+/-1.5x implied move if inside an earnings
window). Stress ceiling calibrated to THIS book's expected weekly/monthly
P&L (not the index book's 2-4 week benchmark — different return profile).
Any suggestion breaching a bucket is filtered pre-card, breach reason logged.

---

## 8. Execution

N-leg combo builder; whatIf margin check before anything; transmit=False
ALWAYS (stage only, manual transmit in TWS). Mid-price with walk-in logic,
max reprices bounded, never into MOC. OptionStrat deep-links on every card
for out-of-hours review.

---

## 9. Persistence / audit

sqlite: positions; entries with full rationale (regime read, greeks,
sizing, screen snapshot); alerts + resolutions; whatIf results;
blocked_structures learn-table (whatIf rejects). Foundation for a later
edge audit (which triggers/structures actually paid).

---

## 10. UI panels (Flask + browser)

1. Weekly checkpoint dashboard — regime read, screened universe, candidate
   cards per sleeve/account.
2. Open book — positions across accounts, greeks, P&L, DTE.
3. Alerts queue — severity-sorted, actions, OptionStrat link, stage-to-TWS.
4. SMSF view — core holdings vs target weights, wheel state, active hedges.
5. Stress panel — beta-mapped market row + worst-single-name row.

---

## 11. Pacing budget

- Weekly universe screen: ~80 names x (2-pass ATM+25D Fridays-only chain +
  1 IV-history req + 1 daily-history req), under batch-40-and-cancel + TTL
  caches. Documented in screen module docstring; test asserts the request
  count stays within budget.
- Position monitor: open positions only (small N) x marks/greeks, EOD
  (+ optional 3x intraday). Cheap by construction.

---

## 12. Out of scope (parked)

- EVENT EARNINGS family (hold a structure THROUGH a print): high-touch by
  definition — contradicts the low-touch mandate. Deferred. The
  earnings_premium / implied-move machinery is built (SS4) so it can be
  added later cheaply if ever wanted.
- Strategy-spec trade-builder (optimise a chosen per-strategy spec ->
  build exact trade -> OptionStrat -> stage TWS): the separate parked
  objective; after Keystone v1 lands.

---

## Standing doctrine (carried, enforced in code where noted)

Market regime HARD-SKIP vetoes all new entries (never overridden by cadence)
* defined risk everywhere in the trading sleeve * earnings-excluded by
default; ETFs preferred * must-touch-by DTE keeps gamma low between touches
(21 income / 7 any short calendar leg) * assignment-tolerant wheel (no gamma
panic) * single-name gap sized as if max loss is realizable * mid, walk in,
bounded reprices, never into MOC * whatIf transmit=False the final arbiter *
two clocks: slow scheduled entries, fast alert-only defense.
