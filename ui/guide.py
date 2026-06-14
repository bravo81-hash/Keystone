"""Built-in reference guide: the selection criteria, rendered into /guide and
surfaced as hover tooltips across the panels. Single source of truth for the
'why' behind every screen gate, regime state, and strategy.
"""

from __future__ import annotations

from html import escape

# --------------------------------------------------------------------------- #
# Universe screen (stock / ETF eligibility)
# --------------------------------------------------------------------------- #
SCREEN_GATES = [
    ("Last price", "≥ $30", "skip illiquid / low-priced names"),
    ("ATM spread", "≤ 5% of mid (front), ≤ 8% (back)", "tradeable markets only"),
    ("Weekly expiries", "≥ 4 consecutive front weeklies listed", "roll/management flexibility"),
    ("Option ADV", "≥ 5,000 contracts/day", "depth to enter and exit"),
    ("ATM open interest", "≥ 1,000", "resting liquidity near the money"),
    ("Earnings (names)", "next date known + confirmed, else SKIP", "ETFs are exempt"),
]
AFFORDABILITY = (
    "SMSF affordability flag (csp_eligible_smsf): 100 × price ≤ 12% of SMSF NLV "
    "for a single name, or ≤ 25% for a diversified ETF."
)
TIERS = (
    "Tier A = mega-cap / index-like (full weight). Tier B = idiosyncratic "
    "(0.6× multiplier in the ranker, so it needs a better regime to surface)."
)

# --------------------------------------------------------------------------- #
# Regime
# --------------------------------------------------------------------------- #
MARKET_REGIME = [
    ("CALM_TREND", "VIX term in contango + index above a rising 200DMA", "risk-on"),
    ("NEUTRAL", "no stress, no clean trend", "normal sizing"),
    ("DEFENSIVE", "one stress signal (term backwardation or below the 200DMA)", "raises the SMSF collar flag"),
    ("HARD_SKIP", "backwardation + trend break", "VETOES all new entries in both sleeves"),
]
STOCK_REGIME = [
    ("PREMIUM_RICH", "elevated/high IVR + positive VRP", "favor selling premium"),
    ("PREMIUM_FAIR", "middling IVR, non-negative VRP", "premium selling ok"),
    ("PREMIUM_THIN", "IVR below the 30 floor", "avoid selling premium"),
    ("EARNINGS_BLACKOUT", "confirmed earnings imminent (≤ 2 days)", "no new short premium"),
    ("NEUTRAL", "none of the above", ""),
]
BLEND = "Entry score = 0.4 × market regime + 0.6 × per-stock regime. IVR floor of 30 to sell premium."

# --------------------------------------------------------------------------- #
# Strategy families (family value -> criteria)
# --------------------------------------------------------------------------- #
STRATEGIES: dict[str, dict[str, str]] = {
    "put_credit_spread": {
        "sleeve": "Trading", "when": "bullish / neutral, IVR ≥ 30",
        "structure": "short ~20Δ put, long wing sized so max-loss fits the budget",
        "dte": "30–60 (target 45)", "manage": "PT 50% · stop 2× credit · must-touch 21 DTE",
    },
    "call_credit_spread": {
        "sleeve": "Trading", "when": "bearish / neutral, IVR ≥ 30",
        "structure": "short ~20Δ call + long wing", "dte": "30–60 (target 45)",
        "manage": "PT 50% · stop 2× credit · must-touch 21 DTE",
    },
    "iron_condor": {
        "sleeve": "Trading", "when": "range-bound + elevated IVR (≥ 30)",
        "structure": "both shorts ~18Δ, symmetric wings fit the budget",
        "dte": "30–60 (target 45)", "manage": "PT 50% · stop 2× · must-touch 21 DTE",
    },
    "trend_leaps": {
        "sleeve": "Trading", "when": "above rising 200DMA (calls) / below falling (puts)",
        "structure": "deep ITM ~75Δ LEAPS, stock-replacement", "dte": "180–365",
        "manage": "trail stop on trend invalidation · no PT on the long leg",
    },
    "trend_diagonal": {
        "sleeve": "Trading", "when": "trend confirmed, directional carry",
        "structure": "long ~75Δ LEAPS + short ~30Δ monthly", "dte": "long 180–365 / short 21–45",
        "manage": "roll short monthly or at 80% · trail trend stop",
    },
    "trend_debit_spread": {
        "sleeve": "Trading", "when": "trend confirmed",
        "structure": "long ~60Δ / short ~30Δ", "dte": "60–120",
        "manage": "trail trend stop · no PT on the long leg",
    },
    "wheel_csp": {
        "sleeve": "SMSF", "when": "accumulate quality you'd own; no earnings straddle",
        "structure": "cash-secured put ~25Δ, strike ≤ acquire price, cash = strike×100",
        "dte": "30–45", "manage": "PT 50% → redeploy, or allow assignment · roll to avoid unwanted assignment",
    },
    "wheel_cc": {
        "sleeve": "SMSF", "when": "covered call on ≥100 core shares; skip earnings / ex-div windows",
        "structure": "short ~20Δ call (low, rarely called away)", "dte": "30–45",
        "manage": "roll at 21 DTE or 80% profit",
    },
    "collar": {
        "sleeve": "SMSF", "when": "ONLY when market regime is DEFENSIVE",
        "structure": "long ~25Δ put financed by the existing covered call", "dte": "30–45",
        "manage": "event-driven; removed when the regime normalizes",
    },
    "pmcc": {
        "sleeve": "SMSF", "when": "core-replacement (OFF by default — config pmcc_enabled)",
        "structure": "long ~75Δ LEAPS + short ~25Δ monthly", "dte": "long-dated + monthly",
        "manage": "monthly roll",
    },
}

MANDATES = [
    "Trading (3 margin): credit spreads, iron condor, trend LEAPS/diagonal/debit.",
    "SMSF (cash): wheel CSP/CC, collar, PMCC. Assignment-tolerant.",
    "SMSF blocks multi-expiry combos on European cash-settled index options (SPX/RUT/NDX/XSP); "
    "American-style is unrestricted. whatIf is the final arbiter.",
]
BUDGETS = [
    "Defined-risk max-loss per position ≤ 1% NLV; max 6 trading positions; max 2 names per sector.",
    "Aggregate short-premium cap; trend sleeve ≤ 5% NLV; correlation cap.",
    "SMSF: CSP cash-reserve cap; assignment notional ≤ 12% (single) / 25% (ETF) NLV; collar allowance.",
    "Stress: −5% / IV+10 beta-mapped market row + a worst-single-name −15% / IV+15 row.",
]
ALERTS = [
    ("INFO", "profit target hit (50% of max)", "opportunistic close / free capital"),
    ("WARN", "approaching stop · must-touch-by DTE (21 income / 7 calendar) · short strike within X·ATR · roll due · earnings exposure", "checkpoint decision"),
    ("CRITICAL", "stop breached · short strike breached · assignment imminent · pin risk · regime flipped HARD_SKIP", "act now"),
]

# --------------------------------------------------------------------------- #
# Tooltips (inline hover help)
# --------------------------------------------------------------------------- #
def strategy_tip(family_value: str) -> str:
    s = STRATEGIES.get(family_value)
    if not s:
        return ""
    return f"[{s['sleeve']}] {s['when']}. {s['structure']}. DTE {s['dte']}. Manage: {s['manage']}."


TIPS = {
    "passed": "Passed all hard liquidity/earnings gates (see Guide).",
    "tier": "Tier A = mega-cap/index-like (full weight); Tier B = idiosyncratic (0.6× rank).",
    "score": "0.4×market regime + 0.6×per-stock regime, ×tier multiplier.",
    "dte": "Days to expiration.",
    "ivr": "IV rank over the past year; ≥30 required to sell premium.",
    "csp_eligible_smsf": AFFORDABILITY,
}


def tip(key: str) -> str:
    return TIPS.get(key, "")


# --------------------------------------------------------------------------- #
# /guide page body
# --------------------------------------------------------------------------- #
def _rows(items, headers):
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in items)
    return f"<table><tr>{head}</tr>{body}</table>"


def render_guide() -> str:
    strat_rows = [
        (k, v["sleeve"], v["when"], v["structure"], v["dte"], v["manage"])
        for k, v in STRATEGIES.items()
    ]
    workflow = [
        "<b>Weekend homework (slow clock):</b> connect to TWS, pick your account, hit "
        "<b>Run weekly checkpoint</b>. It reads the market regime and scans a watchlist's "
        "option chains (yfinance + Black-Scholes greeks, so it works on a closed market using "
        "Friday's data), then shows candidate cards to study.",
        "<b>Weekday live hours (fast clock):</b> re-run on the day; when a candidate still fits, "
        "click <b>Stage to TWS</b> — it whatIf-checks margin and places the combo UNTRANSMITTED "
        "(transmit=False) in TWS for you to review and send manually.",
        "Data: chains/greeks come from yfinance (free, no subscription); TWS is used for your "
        "accounts and staging. Use the OptionStrat link on each card to visualise the trade.",
    ]
    out = [
        "<p class='muted'>Why a name and a structure get picked — the criteria enforced in code.</p>",
        "<h3>Workflow</h3><ul>" + "".join(f"<li>{w}</li>" for w in workflow) + "</ul>",
        "<h3>Universe screen — stock / ETF eligibility</h3>",
        _rows([(g, c, why) for g, c, why in SCREEN_GATES], ["gate", "threshold", "why"]),
        f"<p class='muted'>{escape(AFFORDABILITY)}</p><p class='muted'>{escape(TIERS)}</p>",
        "<h3>Market regime (the on/off gate)</h3>",
        _rows(MARKET_REGIME, ["state", "criteria", "effect"]),
        "<h3>Per-stock regime (selection + sizing)</h3>",
        _rows([(s, c, e) for s, c, e in STOCK_REGIME], ["state", "criteria", "bias"]),
        f"<p class='muted'>{escape(BLEND)}</p>",
        "<h3>Strategy families</h3>",
        _rows(strat_rows, ["family", "sleeve", "when", "structure", "DTE", "management"]),
        "<h3>Account mandates</h3><ul>" + "".join(f"<li>{escape(m)}</li>" for m in MANDATES) + "</ul>",
        "<h3>Budgets &amp; stress</h3><ul>" + "".join(f"<li>{escape(b)}</li>" for b in BUDGETS) + "</ul>",
        "<h3>Alert severity</h3>",
        _rows(ALERTS, ["severity", "fires on", "action"]),
    ]
    return "".join(out)
