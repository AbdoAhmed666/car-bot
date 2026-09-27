"""Demand forecasting: how many of each item will sell in the next 4 weeks.

A single machine-learning model (gradient-boosted trees with a Poisson loss)
is trained across all items on their weekly sales history. Spare parts sell
in bursts with many empty weeks, so the features describe the recent pace,
how often the item sells at all, how long since it last sold, and the same
weeks a year before (seasons), when there is a year of history.

Nothing is trusted on faith: the backtest hides the last weeks, forecasts
them from the weeks before, and scores every method on the shop's own past:
the model, the model averaged with the 13-week average, moving averages and
Croston's method (the classic rule for intermittent demand). The bot uses
whichever misses least, and nothing if the plain 8-week average (what it
does without a forecast) is best. On the real shop, the first backtest had
the 13-week average ahead of the model (README.md, "The AI part").

    python -m src.forecast              backtest on the snapshot and print the scores
    python -m src.forecast data/demo/snapshot.db     ... on another snapshot (the demo shop)

Runs where the export runs (shop PC / laptop); the results travel in the
snapshot, so the server needs no machine-learning libraries.
"""
import sys
from datetime import datetime

import numpy as np

HORIZON = 4              # weeks forecast at once
MIN_HISTORY = 8          # weeks of history before a week can be a training example
BACKTEST_CUTOFFS = (4, 8, 12, 16)     # weeks back where the backtest pretends "now" is


# --- weekly history ----------------------------------------------------------

def weekly(tables, as_of):
    """(item ids, prices, Y) with Y[item, w] = net pieces sold in week w, week 0 being
    the 7 days up to `as_of`, week 1 the 7 days before, and so on."""
    items = [r for r in tables["items"] if not r[7]]                   # not deleted
    ids = [r[0] for r in items]
    row = {item_id: n for n, item_id in enumerate(ids)}
    prices = np.array([r[4] for r in items], dtype=float)
    dates = {r[0]: r[1] for r in tables["invoices"]}
    ret_dates = {r[0]: r[1] for r in tables["returns"]}
    first = min((d for d in dates.values() if d), default=None)
    if first is None:
        return ids, prices, np.zeros((len(ids), 1))
    weeks = max(1, (as_of - datetime.fromisoformat(first)).days // 7 + 1)
    Y = np.zeros((len(ids), weeks))

    def add(item_id, date, qty):
        if item_id in row and date:
            w = (as_of - datetime.fromisoformat(date)).days // 7
            if 0 <= w < weeks:
                Y[row[item_id], w] += qty

    for _, invoice_id, item_id, qty, *_ in tables["invoice_lines"]:
        add(item_id, dates.get(invoice_id), qty)
    for _, return_id, item_id, qty, *_ in tables["return_lines"]:
        add(item_id, ret_dates.get(return_id), -qty)
    return ids, prices, np.clip(Y, 0, None)


# --- features and target -------------------------------------------------------

FEATURES = ["lag1", "lag2", "lag3", "lag4", "mean4", "mean8", "mean13", "mean26", "mean52",
            "weeks_selling_13", "weeks_since_sale", "trend", "age", "log_price", "last_year_next4"]
YEAR = 52


def features(Y, prices, cutoff):
    """One row per item, from the weeks before `cutoff` only (column cutoff = the latest of those)."""
    H = Y[:, cutoff:]
    n = H.shape[1]

    def mean(k):
        return H[:, :k].mean(axis=1) if n else np.zeros(len(Y))

    def lag(k):
        return H[:, k] if n > k else np.zeros(len(Y))

    sold = H > 0
    any_sold = sold.any(axis=1)
    since = np.where(any_sold, sold.argmax(axis=1), 52).clip(max=52)
    oldest = np.where(any_sold, n - 1 - sold[:, ::-1].argmax(axis=1), 0)
    # the HORIZON weeks being forecast, a year earlier; unknown (NaN) without a year of history
    last_year = (H[:, YEAR - HORIZON:YEAR].sum(axis=1) if n >= YEAR
                 else np.full(len(Y), np.nan))
    X = np.column_stack([
        lag(0), lag(1), lag(2), lag(3), mean(4), mean(8), mean(13), mean(26), mean(YEAR),
        sold[:, :13].mean(axis=1) if n else np.zeros(len(Y)),
        since, mean(4) - mean(13), np.minimum(oldest, 104), np.log1p(prices), last_year])
    return X


def target(Y, cutoff):
    """Pieces sold in the HORIZON weeks right after `cutoff` (the more recent columns)."""
    return Y[:, cutoff - HORIZON:cutoff].sum(axis=1)


def _training_set(Y, prices, newest_cutoff):
    """Examples whose target weeks all lie at or before `newest_cutoff` weeks back."""
    Xs, ys = [], []
    for c in range(newest_cutoff + HORIZON, Y.shape[1] - MIN_HISTORY + 1):
        Xs.append(features(Y, prices, c))
        ys.append(target(Y, c))
    if not Xs:
        return None, None
    return np.vstack(Xs), np.concatenate(ys)


def _model():
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(loss="poisson", learning_rate=0.05, max_iter=300, max_leaf_nodes=15,
                                         min_samples_leaf=50, l2_regularization=1.0, random_state=0)


def fit_predict(Y, prices, cutoff):
    """Train on everything known at `cutoff`, forecast the HORIZON weeks after it."""
    X, y = _training_set(Y, prices, cutoff)
    if X is None or y.sum() == 0:
        return None
    model = _model().fit(X, y)
    return np.clip(model.predict(features(Y, prices, cutoff)), 0, None)


# --- simple rules to beat ------------------------------------------------------

def moving_average(Y, cutoff, weeks):
    return Y[:, cutoff:cutoff + weeks].mean(axis=1) * HORIZON


def croston_sba(Y, cutoff, alpha=0.1):
    """Croston's method with the Syntetos-Boylan correction, per item."""
    out = np.zeros(len(Y))
    for i, series in enumerate(Y[:, cutoff:][:, ::-1]):        # oldest week first
        size = interval = None
        gap = 1
        for y in series:
            if y > 0:
                if size is None:
                    size, interval = y, gap
                else:
                    size += alpha * (y - size)
                    interval += alpha * (gap - interval)
                gap = 1
            else:
                gap += 1
        if size is not None:
            out[i] = (1 - alpha / 2) * size / interval * HORIZON
    return out


# --- every method, and the backtest that picks one -------------------------------

METHODS = ("model", "blend", "average_8_weeks", "average_13_weeks", "croston")
PLAIN = "average_8_weeks"       # what the bot does with no forecast (VELOCITY_DAYS=60)


def predict(Y, prices, cutoff, methods=METHODS) -> dict:
    """{method: pieces expected in the HORIZON weeks after `cutoff`}, or {} if the model can't train."""
    out = {}
    if {"model", "blend"} & set(methods):
        model = fit_predict(Y, prices, cutoff)
        if model is None:
            return {}
        out["model"] = model
        out["blend"] = (model + moving_average(Y, cutoff, 13)) / 2
    for weeks in (8, 13):
        out[f"average_{weeks}_weeks"] = moving_average(Y, cutoff, weeks)
    if "croston" in methods:
        out["croston"] = croston_sba(Y, cutoff)
    return {m: out[m] for m in methods}


def wape(pred, actual):
    """Weighted absolute percentage error: total miss / total sold."""
    total = actual.sum()
    return float(np.abs(pred - actual).sum() / total) if total else float("nan")


def backtest(Y, prices, cutoffs=BACKTEST_CUTOFFS) -> dict:
    """{method: {"wape", "bias"}} over the items that sold in the half year before
    each cutoff. bias: how much more (+) or less (-) it forecast than sold, in total."""
    preds, actuals = {m: [] for m in METHODS}, []
    for c in cutoffs:
        if Y.shape[1] < c + HORIZON + MIN_HISTORY + 4:
            continue
        got = predict(Y, prices, c)
        if not got:
            continue
        active = Y[:, c:c + 26].sum(axis=1) > 0
        actuals.append(target(Y, c)[active])
        for m in METHODS:
            preds[m].append(got[m][active])
    if not actuals:
        return {}
    actual = np.concatenate(actuals)
    return {m: {"wape": wape(np.concatenate(p), actual),
                "bias": float(np.concatenate(p).sum() / actual.sum() - 1) if actual.sum() else float("nan")}
            for m, p in preds.items()}


def best_method(scores) -> str:
    return min(scores, key=lambda m: scores[m]["wape"])


# --- what the export stores ------------------------------------------------------

def forecast_rows(tables, as_of, cutoffs=BACKTEST_CUTOFFS):
    """(rows for the snapshot's forecasts table, meta) or ([], {}) when there is too little history.

    rows: (item id, pieces expected in the next 30 days) from the method that
    missed least in the backtest. meta: which method, the scores, and whether
    the bot should use it (only if it beat the plain 8-week average).
    """
    ids, prices, Y = weekly(tables, as_of)
    if Y.shape[1] < HORIZON + MIN_HISTORY + 8:
        return [], {}
    scores = backtest(Y, prices, cutoffs)
    if not scores:
        return [], {}
    best = best_method(scores)
    now = predict(Y, prices, 0, methods=(best,))
    if not now:
        return [], {}
    per_30_days = 30 / (7 * HORIZON)
    rows = [(item_id, round(float(q) * per_30_days, 3)) for item_id, q in zip(ids, now[best])]
    meta = {"forecast_at": as_of.strftime("%Y-%m-%d %H:%M:%S"),
            "forecast_method": best,
            "forecast_wape": f"{scores[best]['wape']:.4f}",
            "forecast_plain_wape": f"{scores[PLAIN]['wape']:.4f}",
            "forecast_model_wape": f"{scores['model']['wape']:.4f}",
            "forecast_used": "1" if best != PLAIN else "0"}
    return rows, meta


def main(argv=None) -> int:
    """Backtest on the snapshot the bot reads (or the one named), and print the scores."""
    import sqlite3
    from pathlib import Path
    from . import config
    argv = sys.argv[1:] if argv is None else argv
    cfg = config.load()
    path = Path(argv[0]) if argv else cfg.snapshot_path
    if not path.exists():
        print(f"no snapshot at {path}: run python -m src.export (or python -m src.demo)")
        return 1
    db = sqlite3.connect(path)
    tables = {name: db.execute(f"SELECT * FROM {name}").fetchall()
              for name in ("items", "invoices", "invoice_lines", "returns", "return_lines")}
    exported = db.execute("SELECT value FROM meta WHERE key = 'exported_at'").fetchone()
    db.close()
    as_of = cfg.as_of or datetime.fromisoformat(exported[0])
    ids, prices, Y = weekly(tables, as_of)
    print(f"{len(ids):,} items, {Y.shape[1]} weeks of history up to {as_of:%Y-%m-%d}")
    print(f"backtest: forecast {HORIZON} weeks from {', '.join(str(c) for c in BACKTEST_CUTOFFS)} weeks back")
    scores = backtest(Y, prices)
    if not scores:
        print("not enough history to backtest")
        return 1
    best = best_method(scores)
    print(f"  {'method':18} {'WAPE':>6}  {'bias':>6}")
    for name, score in sorted(scores.items(), key=lambda s: s[1]["wape"]):
        print(f"  {name:18} {score['wape']:6.1%}  {score['bias']:+6.0%}{'   <- best' if name == best else ''}")
    print("WAPE: total miss / total sold (lower is better). bias: forecast more (+) or less (-) than sold.")
    plain = scores[PLAIN]["wape"]
    if best == PLAIN:
        print("the plain 8-week average is best: the bot keeps it")
    else:
        print(f"the bot uses {best}: it misses {1 - scores[best]['wape'] / plain:.0%} less than the plain 8-week average")
    return 0


if __name__ == "__main__":
    sys.exit(main())
