# Keystone

Low-touch stock/ETF options **trading + investing** system for Interactive
Brokers (IBKR/TWS). Separate application from any index book — engineering
patterns are re-implemented here, not imported.

- All times anchored to **America/New_York**.
- Execution is **staged only**: `transmit=False` on every order, always. You
  transmit manually in TWS.
- **Two clocks:** a slow scheduled clock (weekly trading checkpoint;
  monthly/quarterly investing rebalance) drives new entries, and a fast
  alert-only clock (EOD position monitor) pings you on exceptions.

See [keystone-design.md](keystone-design.md) for the full design doctrine.

> **Status:** Stage 0 (foundation) complete — config, account profiles, pacing
> IB client, models, Black-Scholes, sqlite store, Flask shell. Later stages
> (universe, events, regime, strategies, selection, portfolio risk, execution,
> alerts, UI) are scaffolded as documented stubs. A full README — architecture,
> module map, config-to-fill, run procedure, and pacing math — lands in Stage 12.

## Layout

```
config/      accounts/universe/investing/risk YAML + pydantic schemas + loaders
core/        ib_client (pacing), models, bs_pricing, context
universe/    seed, weekly screen -> screened.json
events/      earnings (IBKR/Finnhub/CSV), dividends, earnings-premium
regime/      market regime (VIX-complex + trend), per-stock regime, blend
strategies/  credit_spread, iron_condor, trend_long, wheel_csp/cc, collar, pmcc
selection/   ranker (mandate filter -> per-sleeve candidates -> cards)
portfolio/   account_profiles, budgets, stress, fit
alerts/      monitor, triggers, alert_store, intraday stub
execution/   n_leg_combo, whatif, mid_walk_in, optionstrat_links
store/        sqlite audit (positions, entries, alerts, snapshots, whatif, blocked)
ui/          Flask + browser panels
tests/       pytest suite (MockIB; no live TWS in CI)
```

## Quick start

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     POSIX: source .venv/bin/activate
pip install -r requirements.txt
pytest                       # run the test suite (uses MockIB, no TWS)
python -m ui.app             # start the Flask shell; GET /health
```

For live TWS data/execution: `pip install -r requirements-live.txt` and run
TWS/Gateway with the API enabled.
