"""The demand forecast: history, features without peeking ahead, backtest."""
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime

import numpy as np
import pytest

from src import forecast
from src.reports import Reports
from src.shop import Shop
from src.state import State
from tests import fake_shop

AS_OF = datetime(2026, 9, 26, 23, 30)


def tiny_tables():
    items = [(1, "a", "", 5, 100.0, 70.0, 1, 0), (2, "b", "", 0, 50.0, 30.0, 1, 0), (3, "gone", "", 0, 1, 1, 1, 1)]
    invoices = [(1, "2026-09-26 10:00:00", 2, 0, 0, 0, 1, 0),      # week 0
                (2, "2026-09-18 10:00:00", 2, 0, 0, 0, 1, 0),      # week 1
                (3, "2026-09-05 10:00:00", 2, 0, 0, 0, 1, 0)]      # week 3
    lines = [(1, 1, 1, 2.0, 0, 0, 0), (2, 2, 1, 3.0, 0, 0, 0), (3, 3, 2, 4.0, 0, 0, 0), (4, 1, 3, 9.0, 0, 0, 0)]
    returns = [(1, "2026-09-26 12:00:00", 2, 0, 0)]
    return_lines = [(1, 1, 1, 1.0, 0, 0)]
    return {"items": items, "invoices": invoices, "invoice_lines": lines, "returns": returns,
            "return_lines": return_lines}


def test_weekly_history():
    ids, prices, Y = forecast.weekly(tiny_tables(), datetime(2026, 9, 26, 23, 0))
    assert ids == [1, 2]                                   # the deleted item is left out
    assert list(prices) == [100.0, 50.0]
    assert Y.shape == (2, 4)
    assert list(Y[0]) == [1.0, 3.0, 0.0, 0.0]              # 2 sold - 1 returned in week 0
    assert list(Y[1]) == [0.0, 0.0, 0.0, 4.0]


def test_features_only_see_the_past():
    rng = np.random.default_rng(0)
    Y = rng.poisson(1.0, size=(20, 40)).astype(float)
    prices = np.full(20, 100.0)
    before = forecast.features(Y, prices, 10)
    Y[:, :10] = 999                                        # the future changes...
    assert np.array_equal(before, forecast.features(Y, prices, 10), equal_nan=True)   # ...the features don't
    assert forecast.target(Y, 10).tolist() == Y[:, 6:10].sum(axis=1).tolist()


def test_last_year_feature_needs_a_year():
    Y = np.arange(60, dtype=float)[None, :].repeat(2, axis=0)      # column w holds w
    col = forecast.FEATURES.index("last_year_next4")
    X = forecast.features(Y, np.full(2, 10.0), 4)                 # 56 weeks of history
    assert X[0, col] == sum(range(4 + 48, 4 + 52))                # the 4 target weeks, a year back
    assert np.isnan(forecast.features(Y, np.full(2, 10.0), 10)[0, col])   # 50 weeks: unknown
    assert X.shape[1] == len(forecast.FEATURES)


def test_croston_on_steady_demand():
    Y = np.ones((1, 30))
    assert forecast.croston_sba(Y, 0)[0] == pytest.approx((1 - 0.05) * 1 * forecast.HORIZON)


def test_backtest_and_rows_on_the_fake_shop():
    from src import export
    tables = export.transform(fake_shop.source_rows())
    ids, prices, Y = forecast.weekly(tables, AS_OF)
    scores = forecast.backtest(Y, prices)
    assert set(scores) == set(forecast.METHODS)
    assert all(0 < v["wape"] < 1 and -1 <= v["bias"] < 1 for v in scores.values())
    rows, meta = forecast.forecast_rows(tables, AS_OF)
    assert len(rows) == 35 and all(q >= 0 for _, q in rows)
    best = forecast.best_method(scores)
    assert meta["forecast_method"] == best
    assert float(meta["forecast_wape"]) == pytest.approx(scores[best]["wape"], abs=1e-4)
    assert meta["forecast_used"] == ("0" if best == forecast.PLAIN else "1")

    # the rows are that method's forecast, per 30 days
    expected = forecast.predict(Y, prices, 0, methods=(best,))[best] * 30 / 28
    assert [q for _, q in rows] == pytest.approx(expected.tolist(), abs=1e-3)


def test_forecast_is_made_once_a_day(tmp_path, monkeypatch):
    from src import export
    path = fake_shop.snapshot(tmp_path / "snap.db")
    made = []
    monkeypatch.setattr(forecast, "forecast_rows", lambda *a, **k: made.append(1) or ([(1, 9.0)], {}))
    tables = export.transform(fake_shop.source_rows())
    same_day, meta = export.with_forecasts(tables, fake_shop.EXPORTED_AT.replace(hour=22), reuse_from=path)
    assert not made and len(same_day["forecasts"]) == 35 and "forecast_method" in meta
    next_day, _ = export.with_forecasts(tables, datetime(2026, 9, 27, 11), reuse_from=path)
    assert made and next_day["forecasts"] == [(1, 9.0)]


@pytest.fixture
def model_on(shop_cfg, tmp_path):
    """The fake snapshot, but as if the model had won its backtest."""
    path = tmp_path / "model.db"
    shutil.copy(shop_cfg.snapshot_path, path)
    db = sqlite3.connect(path)
    db.execute("UPDATE meta SET value = '1' WHERE key = 'forecast_used'")
    db.execute("UPDATE meta SET value = 'model' WHERE key = 'forecast_method'")
    db.execute("UPDATE meta SET value = '0.3' WHERE key = 'forecast_wape'")
    db.execute("UPDATE meta SET value = '0.4' WHERE key = 'forecast_plain_wape'")
    db.commit()
    db.close()
    return replace(shop_cfg, snapshot_path=path)


def test_bot_uses_the_forecast_only_when_it_beat_the_average(shop_cfg, model_on):
    assert Shop(shop_cfg).forecasts() == {}                # lost the backtest: not used
    assert len(Shop(model_on).forecasts()) == 35

    reports = Reports(Shop(model_on), model_on, State(model_on.state_path), as_of=AS_OF)
    card = reports.ask("موبينه سيراتو").text
    assert "📈 متوقع يتباع منه في الـ30 يوم الجايين: حوالي" in card
    assert ("🤖 التوقع بطريقة موديل تعلّم آلي: أدق طريقة على مبيعات المحل، "
            "غلطها أقل من المتوسط العادي بـ 25%") in reports.weekly().text
    plain = Reports(Shop(shop_cfg), shop_cfg, State(shop_cfg.state_path), as_of=AS_OF)
    assert "📈" not in plain.ask("موبينه سيراتو").text and "🤖" not in plain.weekly().text
    assert "📐" not in plain.weekly().text
