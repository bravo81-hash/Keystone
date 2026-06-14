# Keystone

Low-touch stock/ETF options **trading + investing** system for Interactive
Brokers (IBKR/TWS). A standalone application — engineering patterns are
re-implemented here, not imported from any index book.

- All times anchored to **America/New_York**.
- Execution is **staged only**: `transmit=False` on every order, always. You
  transmit manually in TWS after reviewing the staged combo.
- Market-regime **HARD_SKIP vetoes all new entries** and is never softened by
  the forced weekly cadence.

See [keystone-design.md](keystone-design.md) for the full doctrine. Status:
all 12 build stages complete; 220 tests passing (MockIB — no live TWS in CI).

## The two-clock model

Keystone is low-touch-but-responsive via two independent clocks:

- **Slow clock (you drive it).** A fixed weekly trading checkpoint (new entries
  + roll decisions) and a monthly/quarterly SMSF rebalance to target weights.
  The pacing-heavy universe screen and regime refresh run here.
- **Fast clock (alert-only, automated).** An EOD monitor marks the *open*
  positions (small N) and emits severity-ranked alerts; you act within days
  only when one fires. Optional 3x/day intraday hook exists but is off by
  default.

Two pools, separate mandates and budgets:

| Pool | Accounts | Mandate |
|---|---|---|
| Trading | 3 margin | defined-risk short premium + small long-premium trend convexity |
| Investing | 1 SMSF (cash) | wheel-driven accumulation + protected core; assignment-tolerant |

The SMSF's only structural restriction is **multi-expiry combos on European
cash-settled index options (SPX/RUT/NDX/XSP)**; American-style instruments are
unrestricted. whatIf is the final arbiter; rejects are logged to a learn-table.

## Module map

```
config/      pydantic schemas + YAML loaders (accounts/universe/investing/risk)
core/        ib_client (pacing), models, chain, bs_pricing, context (TradeContext)
universe/    seed (~95 names/ETFs), screen -> screened.json
events/      base, earnings (CSV/IBKR/Finnhub), dividends, earnings_premium
regime/      surface, vol_history (IVR/RV/VRP), skew, stock_regime,
             market_regime, blend (0.4/0.6 + HARD_SKIP veto), proximity
strategies/  _guards, _common, credit_spread, iron_condor, trend_filter,
             trend_long, wheel_csp, wheel_cc, collar, pmcc(off)
selection/   ranker (mandate filter -> candidates -> score -> fit -> cards)
portfolio/   account_profiles, budgets, stress, fit, rebalance, index_book(off)
execution/   n_leg_combo, whatif, mid_walk_in, optionstrat_links, stage(_to_tws)
alerts/      triggers, monitor (EOD), alert_store, intraday(off)
ui/          Flask app + AppState + 5 panels
store/       sqlite audit (positions, entries, alerts, screen_snapshots,
             whatif_results, blocked_structures)
tests/       pytest suite (MockIB)
```

## Quick start

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     POSIX: source .venv/bin/activate
pip install -r requirements.txt
pytest                       # 242 tests, uses MockIB (no TWS)
python -m ui.app             # dark-theme UI; opens in MOCK mode (populated demo)
```

The UI starts in **mock mode** — a fully populated demo (real ranker cards,
alerts, stress) so you can explore without TWS. Switch to **live** from the
status bar. A built-in **Guide** documents every selection criterion (screen
gates, regime states, per-strategy rules, mandates, budgets, alert severities),
and key terms have hover tooltips.

Live TWS data/execution: `pip install -r requirements-live.txt` and run
TWS/Gateway with the API enabled.

## Connecting to TWS, accounts, and data sources

- **TWS connection.** Defaults to `127.0.0.1:7496` (live; 7497 = paper). Each
  operation opens a fresh, short-lived connection with a **dynamic clientId**
  (random, retried on collision) in its own thread/event loop — so Keystone
  never clashes with your other apps connected to the same TWS
  (`core.ib_client.with_ib` / `connect_ib`).
- **Account selection.** Open **Connect** (status bar) to list your TWS managed
  accounts + NLV (`managedAccounts` + `accountSummary`); click **select** to set
  the active account. Each account's pool/mandate drives candidate generation
  and staging.
- **Data fallback.** When live TWS data isn't available, Keystone falls back
  automatically: **TWS → yfinance → Finnhub (free tier)**
  (`core.market_data.build_market_data`). yfinance needs no key; Finnhub uses
  your saved key for last-price quotes.
- **API key, saved once.** Enter your Finnhub key on the **Settings** page; it's
  written to `~/.keystone/secrets.yaml` (override the dir with `KEYSTONE_HOME`)
  and reused every run — no re-entering. An env var (`FINNHUB_KEY`,
  `KEYSTONE_TWS_HOST/PORT`) still overrides the saved value when set.

## Config files to fill (before live use)

- [config/accounts.yaml](config/accounts.yaml) — **replace placeholder
  `account_id`s with your real IBKR ids and set each `nlv`.** Default topology
  is 3 trading (margin) + 1 SMSF (cash) with the EU-cash-index multi-expiry block.
- [config/investing.yaml](config/investing.yaml) — **`target_holdings` is a
  placeholder scaffold; review/replace** with your SMSF core (ticker,
  target_weight, acquire_below_price, is_etf). `pmcc_enabled` defaults False.
- [config/universe.yaml](config/universe.yaml) — screen gate thresholds + SMSF
  affordability percentages.
- [config/risk.yaml](config/risk.yaml) — trading + SMSF budgets and stress
  parameters. **Set `stress.weekly_pnl_ceiling`** to this book's expected P&L.
- [data/earnings_manual.csv](data/earnings_manual.csv) — manual earnings dates
  (overrides IBKR/Finnhub). Keep current for names you trade.
- `FINNHUB_KEY` env var — optional earnings fallback.

## Weekly checkpoint scan (the homework engine)

In **live** mode, **Connect** → pick your account → **Run weekly checkpoint**.
The scan reads the market regime (VIX complex + SPY/200DMA) and builds option
chains for a watchlist from **yfinance with Black-Scholes-computed greeks** — so
it needs no market-data subscription and works on a closed market using Friday's
data (ideal for weekend prep). It runs the screen → regime → ranker and shows
**candidate cards** with legs, net **credit/debit**, max profit/loss, **greeks**,
an **OptionStrat** link, and a **Stage to TWS** button. Staging runs a whatIf
margin check and places the combo **untransmitted** (`transmit=False`) in TWS for
you to review and send manually. (Chains/greeks via yfinance; TWS for accounts +
staging.)

## Run procedure

**Weekly checkpoint (slow clock):**
1. On a Friday, refresh chains + run the universe screen -> `screened.json`.
2. Refresh per-stock surface/IVR/VRP/skew and the market regime.
3. Ranker produces account/sleeve cards (mandate-filtered, budget-checked).
4. Review cards in the dashboard; `stage_to_tws` the ones you want (whatIf,
   `transmit=False`), then transmit manually in TWS.

**EOD (fast clock):** run the monitor over open positions; act on alerts
(severity-sorted) using the suggested action + OptionStrat link + stage-to-TWS.

**Monthly/quarterly:** SMSF rebalance — underweight core names route to the
wheel (CSP).

## Pacing math

**Weekly universe refresh (Stage 3 audit, `regime/vol_history.py`).** Per name,
once per week with caches warm: 1 chain (Fridays-only) + 1 IV-history +
1 daily-history = **3 metadata requests**. For 80 names that is 80 CHAIN +
160 HISTORICAL = **240 requests/week**, plus ATM+25-delta quote snapshots issued
via `fetch_quotes` (batched **40-and-cancel**, never more than 40 streaming lines
open at once). The daily TRADES fetch is cached once and shared by RV20 and the
earnings realized-moves. TWS pacing (~60 identical historical/10min, 50
simultaneous, 100 market-data lines) is never approached at a weekly cadence.
`tests/test_pacing.py` asserts the per-name math and that warm caches add zero
requests.

**Position monitor (Stage 11, `alerts/intraday.py`).** Reads only *open*
positions (small N) — marks + greeks — EOD, optionally 3x/day. No chain/history
requests intraday. A book of ≤6 trading + a few SMSF positions is a few dozen
batched snapshots per run, far inside TWS limits.
