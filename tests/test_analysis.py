from datetime import datetime, timedelta

from src import analysis
from src.shop import Item, ItemSales

NOW = datetime(2026, 9, 26, 23, 0)


def view(stock, sold, cost=100, last_days_ago=1, window=60, id=1, price=150):
    item = Item(id, f"صنف {id}", "", stock, price, cost)
    last = NOW - timedelta(days=last_days_ago) if last_days_ago is not None else None
    return analysis.views([item], {id: ItemSales(qty=sold, revenue=sold * price)}, {id: last}, window)[id]


def test_cover_days_and_reorder():
    v = view(stock=6, sold=60)                  # 1 a day
    assert v.cover_days == 6
    assert analysis.reorder_qty(v) == 24        # a month is 30, 6 in stock


def test_running_low_out_of_stock_first_and_min_sold():
    out = view(stock=0, sold=30, id=1)
    soon = view(stock=3, sold=60, id=2)
    fine = view(stock=100, sold=60, id=3)
    rare = view(stock=0, sold=2, id=4)          # below min_sold: not "in demand"
    low = analysis.running_low([fine, soon, rare, out], max_days=7, min_sold=3)
    assert [v.item.id for v in low] == [1, 2]


def test_negative_stock_counts_as_out():
    assert view(stock=-3, sold=30).cover_days == 0


def test_idle_and_advice():
    old = view(stock=10, sold=0, last_days_ago=400, id=1, cost=50)
    mid = view(stock=10, sold=0, last_days_ago=200, id=2, cost=100)
    recent = view(stock=10, sold=0, last_days_ago=100, id=3, cost=10)
    never = view(stock=10, sold=0, last_days_ago=None, id=4, cost=5)
    sold_lately = view(stock=10, sold=5, last_days_ago=20, id=5)
    empty = view(stock=0, sold=0, last_days_ago=400, id=6)
    idle = analysis.idle([old, mid, recent, never, sold_lately, empty], NOW, idle_days=90)
    assert [v.item.id for v in idle] == [2, 1, 3, 4]            # most money first
    assert analysis.idle_advice(old, NOW) == "بيعه بخصم أو رجّعه للمورد"
    assert analysis.idle_advice(never, NOW) == "بيعه بخصم أو رجّعه للمورد"
    assert analysis.idle_advice(mid, NOW) == "اعمل عليه عرض"
    assert analysis.idle_advice(recent, NOW) == "وقّف طلبه لحد ما يتحرك"


def test_slow_movers():
    slow = view(stock=300, sold=60)             # 300 days of stock
    normal = view(stock=30, sold=60, id=2)
    assert analysis.slow_movers([slow, normal]) == [slow]


def test_changes_since_snapshot():
    snapshot = {1: {"price": 100, "cost": 70, "stock": 5},
                2: {"price": 50, "cost": 30, "stock": 2},
                3: {"price": 80, "cost": 60, "stock": 1}}
    items = [Item(1, "a", "", 5, 110, 70), Item(2, "b", "", 20, 50, 30),
             Item(3, "c", "", 0, 80, 60), Item(4, "d", "", 3, 10, 5)]
    ch = analysis.changes(snapshot, items)
    assert [(i.id, old) for i, old in ch["price"]] == [(1, 100)]
    assert [(i.id, old) for i, old in ch["arrived"]] == [(2, 2)]
    assert [i.id for i in ch["ran_out"]] == [3]
    assert [i.id for i in ch["new"]] == [4]


def test_totals_with_returns():
    invoices = [{"total": 1000, "profit": 250, "credit": True}, {"total": 500, "profit": 100, "credit": False}]
    returns = [{"total": 200, "profit": -40}]
    t = analysis.totals(invoices, returns)
    assert (t["count"], t["total"], t["credit_total"]) == (2, 1500, 1000)
    assert (t["net_total"], t["net_profit"]) == (1300, 310)


def test_below_cost_and_negative():
    items = [Item(1, "a", "", 5, 90, 100), Item(2, "b", "", -2, 150, 100), Item(3, "c", "", 1, 0, 100)]
    assert [i.id for i in analysis.below_cost(items)] == [1]      # price 0 = not set, ignored
    assert [i.id for i in analysis.negative_stock(items)] == [2]


# --- customers -----------------------------------------------------------------

def test_stopped_buying_is_relative_to_each_customer():
    from src.shop import Customer
    def cv(id, gap, last_days_ago, monthly):
        return analysis.CustomerView(customer=Customer(id, f"عميل {id}"), usual_gap=gap,
                                     last_buy=NOW - timedelta(days=last_days_ago), monthly=monthly)
    weekly_buyer_gone = cv(1, 3, 30, 1000)      # every 3 days, 30 days quiet: stopped
    monthly_buyer = cv(2, 30, 30, 5000)         # every month, 30 days: normal
    small_gone = cv(3, 2, 25, 100)              # stopped too, buys less
    too_recent = cv(4, 2, 10, 900)              # under 21 days: not yet
    long_gone = cv(5, 2, 400, 900)              # over a year: an old customer, not news
    unknown = analysis.CustomerView(customer=Customer(6, "x"), usual_gap=None, last_buy=NOW - timedelta(days=90))
    got = analysis.stopped_buying([weekly_buyer_gone, monthly_buyer, small_gone, too_recent, long_gone, unknown], NOW)
    assert [v.customer.id for v in got] == [1, 3]                  # the bigger one first


def test_walk_in_is_not_a_customer():
    from src.shop import Customer
    assert analysis.is_walk_in(Customer(1, "نقــــدى"))
    assert not analysis.is_walk_in(Customer(2, "ورشة الفجر"))


def test_late_payers_owe_money_and_are_late_for_them():
    from src.shop import Customer
    def cv(id, balance, paid_days_ago, pay_gap=None):
        return analysis.CustomerView(customer=Customer(id, f"عميل {id}"), balance=balance,
                                     first_buy=NOW - timedelta(days=300), usual_pay_gap=pay_gap,
                                     last_payment=NOW - timedelta(days=paid_days_ago) if paid_days_ago else None)
    weekly_payer_late = cv(1, 50_000, 35, 7)       # pays weekly, 35 days since: late
    monthly_payer = cv(2, 80_000, 35, 30)         # pays monthly: 35 days is normal (under 2 x 30)
    small = cv(3, 500, 90, 7)                     # owes too little to chase
    never_paid = cv(4, 20_000, None)              # no payment since first buying, 300 days ago
    recent = cv(5, 90_000, 10, 7)                 # paid 10 days ago
    in_credit = cv(6, -1_700, 200)                # the shop owes them
    got = analysis.late_payers([weekly_payer_late, monthly_payer, small, never_paid, recent, in_credit], NOW)
    assert [v.customer.id for v in got] == [1, 4]                  # who owes the most first
    assert [v.customer.id for v in analysis.owing([small, in_credit, recent])] == [5, 3]
    unknown = analysis.CustomerView(customer=Customer(7, "x"))     # a snapshot without balances
    assert analysis.owing([unknown]) == [] and analysis.late_payers([unknown], NOW) == []


def _cv(**kw):
    """A customer with a steady record unless told otherwise."""
    from src.shop import Customer
    base = dict(customer=Customer(1, "تاجر"), life_invoices=100, life_total=200_000, life_profit=44_000,
                first_buy=NOW - timedelta(days=300), last_buy=NOW - timedelta(days=1), usual_gap=2,
                balance=20_000, balance_before=20_000, bought_recent=60_000, paid_recent=60_000,
                last_payment=NOW - timedelta(days=5), usual_pay_gap=7, recent_monthly=20_000, before_monthly=20_000)
    base.update(kw)
    return analysis.CustomerView(**base)


def _signs(v, margin=0.22):
    verdict = analysis.assess(v, NOW, margin)
    return verdict.level, [s for s, _ in verdict.bad], [s for s, _ in verdict.good]


def test_verdict_good_customer():
    assert _signs(_cv()) == ("good", [], ["pays_well"])
    assert _signs(_cv(balance=0, balance_before=0)) == ("good", [], ["pays_well", "clear"])
    assert _signs(_cv(balance=-40_000, balance_before=0))[2] == ["pays_well"]      # the shop owes them: not "clear"
    assert _signs(_cv(recent_monthly=30_000))[2] == ["pays_well", "buys_more"]


def test_verdict_signs_and_how_serious():
    # owes 5,000+ and stopped buying: risky, however much they used to buy
    level, bad, _ = _signs(_cv(last_buy=NOW - timedelta(days=45), bought_recent=0, paid_recent=0))
    assert level == "risk" and bad[0] == "stopped"
    # same with little owed: only worth a look
    assert _signs(_cv(last_buy=NOW - timedelta(days=45), balance=2000, balance_before=2000))[:2] == ("watch", ["stopped"])
    # not paying for far longer than usual
    level, bad, _ = _signs(_cv(last_payment=NOW - timedelta(days=40), paid_recent=0, balance=60_000))
    assert level == "risk" and bad[0] == "not_paying"
    # takes much more than they pay, and the debt grows
    assert _signs(_cv(paid_recent=24_000, balance=56_000))[:2] == ("risk", ["takes_more"])
    assert _signs(_cv(paid_recent=42_000, balance=38_000))[:2] == ("watch", ["takes_more"])
    # what they owe, in months of what they take
    assert _signs(_cv(balance=80_000, balance_before=80_000))[:2] == ("watch", ["debt_months"])      # 4 months
    assert _signs(_cv(balance=140_000, balance_before=140_000))[:2] == ("risk", ["debt_months"])     # 7 months
    # ... unless they are bringing it down: paying more than they take
    assert _signs(_cv(balance=80_000, balance_before=100_000, paid_recent=80_000)) == ("good", [], ["pays_well"])
    assert _signs(_cv(balance=140_000, balance_before=160_000, paid_recent=80_000))[:2] == ("watch", ["debt_months"])
    # buys much less than before, earns little, sends much back
    assert _signs(_cv(recent_monthly=8_000))[:2] == ("watch", ["buys_less"])
    assert _signs(_cv(life_profit=16_000))[:2] == ("watch", ["low_margin"])                          # 8% vs 22%
    assert _signs(_cv(life_returns=30_000))[:2] == ("watch", ["returns"])


def test_verdict_new_and_unknown():
    assert _signs(_cv(life_invoices=3))[0] == "new"
    assert _signs(_cv(first_buy=NOW - timedelta(days=30)))[0] == "new"
    assert _signs(_cv(life_invoices=3, last_payment=NOW - timedelta(days=70), paid_recent=0))[0] == "risk"
    # a snapshot without balances: judged on buying only
    unknown = _cv(balance=None, balance_before=None, bought_recent=0, paid_recent=0, last_payment=None)
    assert _signs(unknown) == ("good", [], [])


def test_lists_by_level():
    from src.shop import Customer
    views = [_cv(customer=Customer(1, "a"), balance=140_000, balance_before=140_000),
             _cv(customer=Customer(2, "b"), paid_recent=24_000, balance=56_000),
             _cv(customer=Customer(3, "c"), life_profit=50_000), _cv(customer=Customer(4, "d"), life_profit=60_000)]
    analysis.rate(views, NOW)
    assert [v.customer.id for v in analysis.by_level(views, "risk")] == [1, 2]      # most money at stake first
    assert [v.customer.id for v in analysis.by_level(views, "good")] == [4, 3]      # most profit first
