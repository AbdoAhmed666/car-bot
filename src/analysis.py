"""What the shop's numbers mean: how long stock lasts, what is running out,
what sits unsold. Plain functions over Shop data, testable without a database."""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from .normalize import normalize


@dataclass
class ItemView:
    item: object                # shop.Item
    sold: float = 0.0           # net quantity sold in the window
    revenue: float = 0.0
    profit: float = 0.0
    per_day: float = 0.0        # expected daily sales: the model's forecast, or the window's average
    last_sale: datetime = None  # latest sale ever (None = never sold)
    forecast_30: float = None   # the model's forecast for the next 30 days, when it is used

    @property
    def cover_days(self):
        """How many days the stock lasts at the current pace; None if it doesn't sell."""
        if self.per_day <= 0:
            return None
        return max(self.item.stock, 0) / self.per_day

    @property
    def money(self):
        """Money sitting in the stock, at cost."""
        return max(self.item.stock, 0) * self.item.cost


def views(items, sales, last_sales, window_days, forecasts=None) -> dict:
    """One ItemView per item. sales: {id: ItemSales} over the last `window_days`.
    forecasts: {id: pieces in the next 30 days}; when given, the pace comes from it."""
    out = {}
    for i in items:
        s = sales.get(i.id)
        v = ItemView(item=i, last_sale=last_sales.get(i.id))
        if s:
            v.sold, v.revenue, v.profit = max(s.qty, 0), s.revenue, s.profit
            v.per_day = v.sold / window_days
        if forecasts and i.id in forecasts:
            v.forecast_30 = forecasts[i.id]
            v.per_day = v.forecast_30 / 30
        out[i.id] = v
    return out


def running_low(all_views, max_days, min_sold) -> list:
    """Items that sell (at least `min_sold` in the window) and have `max_days` of stock
    or less, out-of-stock first, then the soonest to run out."""
    low = [v for v in all_views if v.sold >= min_sold and v.per_day * 30 >= 1
           and v.cover_days is not None and v.cover_days <= max_days]
    return sorted(low, key=lambda v: (v.cover_days, -v.revenue))


def reorder_qty(view, days=30) -> int:
    """How many to order so the stock lasts `days` at the current pace."""
    return max(1, math.ceil(view.per_day * days - max(view.item.stock, 0)))


def slow_movers(all_views, min_cover_days=180) -> list:
    """Items that still sell, but so slowly that the stock lasts half a year or more."""
    slow = [v for v in all_views if v.sold > 0 and v.item.stock > 0 and v.cover_days >= min_cover_days]
    return sorted(slow, key=lambda v: -v.money)


def idle(all_views, now, idle_days) -> list:
    """In stock, and no sale for `idle_days` or more (or never). Most money first."""
    cutoff = now - timedelta(days=idle_days)
    out = [v for v in all_views
           if v.item.stock > 0 and (v.last_sale is None or v.last_sale < cutoff)]
    return sorted(out, key=lambda v: -v.money)


def idle_advice(view, now) -> str:
    days = (now - view.last_sale).days if view.last_sale else None
    if days is None or days >= 365:
        return "بيعه بخصم أو رجّعه للمورد"
    if days >= 180:
        return "اعمل عليه عرض"
    return "وقّف طلبه لحد ما يتحرك"


def below_cost(items) -> list:
    """Items whose sale price is under their cost."""
    return sorted((i for i in items if 0 < i.price < i.cost), key=lambda i: i.price - i.cost)


def negative_stock(items) -> list:
    """Stock below zero: sold more than was ever entered, usually a purchase not recorded."""
    return sorted((i for i in items if i.stock < 0), key=lambda i: i.stock)


def changes(snapshot, items) -> dict:
    """What moved since the last snapshot ({id: {"price", "cost", "stock"}})."""
    out = {"price": [], "arrived": [], "ran_out": [], "new": []}
    for i in items:
        old = snapshot.get(i.id)
        if old is None:
            out["new"].append(i)
            continue
        if abs((old["price"] or 0) - i.price) >= 0.01:
            out["price"].append((i, old["price"] or 0))
        if i.stock > (old["stock"] or 0):
            out["arrived"].append((i, old["stock"] or 0))
        if i.stock <= 0 < (old["stock"] or 0):
            out["ran_out"].append(i)
    return out


def totals(invoices, returns=()) -> dict:
    """Sales totals; the program's invoice Total and Profit are already net of the cash discount."""
    t = {
        "count": len(invoices),
        "total": sum(x["total"] for x in invoices),
        "profit": sum(x["profit"] for x in invoices),
        "credit_count": sum(1 for x in invoices if x["credit"]),
        "credit_total": sum(x["total"] for x in invoices if x["credit"]),
        "returns_count": len(returns),
        "returns_total": sum(r["total"] for r in returns),
        "returns_profit": sum(r["profit"] for r in returns),     # negative
    }
    t["net_total"] = t["total"] - t["returns_total"]
    t["net_profit"] = t["profit"] + t["returns_profit"]
    return t


def losing_lines(lines) -> list:
    """Sale lines sold below cost."""
    return [line for line in lines if line["profit"] < -0.01]


def weekly_value(view) -> float:
    """Money this item brings in a week at its current pace (pieces a week x the price it sold at)."""
    if view.sold <= 0:
        return 0.0
    return view.per_day * 7 * view.revenue / view.sold


def needed(all_views, max_days, min_sold) -> list:
    """Out of stock or running low, the ones that bring in the most money first."""
    return sorted(running_low(all_views, max_days, min_sold), key=lambda v: -weekly_value(v))


# --- customers -----------------------------------------------------------------

RECENT_DAYS = 90            # "lately", for activity and payments

@dataclass
class CustomerView:
    customer: object              # shop.Customer
    invoices: int = 0             # in the window
    total: float = 0.0            # in the window, returns subtracted
    profit: float = 0.0
    credit_total: float = 0.0
    first_buy: datetime = None    # ever
    last_buy: datetime = None     # ever
    usual_gap: float = None       # their usual days between two purchases; None if too few to tell
    monthly: float = 0.0          # what they buy in an average month, over their whole history
    balance: float = None         # what they owe now (negative: the shop owes them); None if unknown
    last_payment: datetime = None
    last_payment_amount: float = 0.0
    usual_pay_gap: float = None   # their usual days between two payments; None if too few to tell
    # since their first invoice
    life_invoices: int = 0
    life_total: float = 0.0       # returns subtracted
    life_profit: float = 0.0
    life_returns: float = 0.0
    # the last RECENT_DAYS against before
    recent_monthly: float = 0.0   # bought per month lately
    before_monthly: float = None  # per month before that; None with under two months of history
    balance_before: float = None  # what they owed RECENT_DAYS ago
    bought_recent: float = 0.0    # taken on credit lately
    paid_recent: float = 0.0      # paid lately
    verdict: object = None        # Verdict, from rate()

    def days_since(self, now):
        return (now - self.last_buy).days if self.last_buy else None

    @property
    def pay_ratio(self):
        """Of what they took on credit lately, how much they paid; None if they took little."""
        return self.paid_recent / self.bought_recent if self.bought_recent >= 3000 else None

    @property
    def debt_growth(self):
        if self.balance is None or self.balance_before is None:
            return None
        return self.balance - self.balance_before

    @property
    def debt_months(self):
        """What they owe, in months of what they take on credit lately."""
        if self.balance is None or self.balance < 1000 or self.bought_recent <= 0:
            return None
        return self.balance / (self.bought_recent / (RECENT_DAYS / 30))

    @property
    def activity_change(self):
        """-0.6: buying 60% less per month lately than before."""
        if not self.before_monthly or self.before_monthly < 1000:
            return None
        return self.recent_monthly / self.before_monthly - 1

    @property
    def margin(self):
        return self.life_profit / self.life_total if self.life_total > 0 else None

    def days_since_payment(self, now):
        """Days since they last paid; if they never did, since they first bought."""
        since = self.last_payment or self.first_buy
        return (now.date() - since.date()).days if since else None


def is_walk_in(customer) -> bool:
    """The program's "cash" customer: walk-in sales, not a real customer."""
    return normalize(customer.name) == "نقدي"


def _usual_gap(days):
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    return median(gaps) if len(gaps) >= 4 else None


def customer_views(customers, window, lifetime, purchase_days, balances=None, recent=None, before=None,
                   now=None) -> dict:
    """window / lifetime / recent / before: shop.customer_sales() over the report window,
    all time, the last RECENT_DAYS and before them. balances: shop.balances(since=the
    start of RECENT_DAYS), when the snapshot has them."""
    cutoff = now - timedelta(days=RECENT_DAYS) if now else None
    out = {}
    for c in customers:
        if is_walk_in(c):
            continue
        w, life = window.get(c.id, {}), lifetime.get(c.id)
        v = CustomerView(customer=c, invoices=w.get("invoices", 0), total=w.get("total", 0.0),
                         profit=w.get("profit", 0.0), credit_total=w.get("credit_total", 0.0),
                         usual_gap=_usual_gap(purchase_days.get(c.id, [])))
        if life:
            v.first_buy, v.last_buy = life["first"], life["last"]
            months = max(1.0, (life["last"] - life["first"]).days / 30)
            v.monthly = life["total"] / months
            v.life_invoices, v.life_total, v.life_profit = life["invoices"], life["total"], life["profit"]
            v.life_returns = life.get("returns", 0.0)
        if recent is not None:
            # a customer newer than the window: per month of the time they have been buying
            days = RECENT_DAYS if not (now and v.first_buy) else min(RECENT_DAYS, (now - v.first_buy).days)
            v.recent_monthly = recent.get(c.id, {}).get("total", 0.0) / max(1.0, days / 30)
        old = (before or {}).get(c.id)
        if old and cutoff and (cutoff - old["first"]).days >= 60:
            v.before_monthly = old["total"] / ((cutoff - old["first"]).days / 30)
        if balances:
            b = balances.get(c.id, {"balance": 0.0, "payments": []})
            v.balance = b["balance"]
            if "before" in b:
                v.balance_before, v.bought_recent, v.paid_recent = b["before"], b["bought"], b["paid"]
            if b["payments"]:
                v.last_payment, v.last_payment_amount = b["payments"][-1]
                v.usual_pay_gap = _usual_gap(sorted({d.replace(hour=0, minute=0, second=0) for d, _ in b["payments"]}))
        out[c.id] = v
    return out


def top_customers(cviews) -> list:
    """Most profit in the window first."""
    return sorted((v for v in cviews if v.invoices), key=lambda v: -v.profit)


def stopped_buying(cviews, now, factor=3, min_days=21, max_days=365) -> list:
    """Regular customers who have gone far longer than usual without buying:
    at least `factor` times their usual gap, and at least `min_days`. The ones
    who used to buy the most first."""
    out = []
    for v in cviews:
        since = v.days_since(now)
        if v.usual_gap is None or since is None:
            continue
        if min_days <= since <= max_days and since >= factor * max(v.usual_gap, 1):
            out.append(v)
    return sorted(out, key=lambda v: -v.monthly)


def new_customers(cviews, now, days=30) -> list:
    since = now - timedelta(days=days)
    return sorted((v for v in cviews if v.first_buy and v.first_buy >= since), key=lambda v: v.first_buy)


def owing(cviews, min_balance=1.0) -> list:
    """Customers who owe the shop money, most first."""
    return sorted((v for v in cviews if v.balance is not None and v.balance >= min_balance),
                  key=lambda v: -v.balance)


def late_payers(cviews, now) -> list:
    """Customers late paying (is_late), the ones who owe the most first."""
    return [v for v in owing(cviews) if is_late(v, now)]


# --- keep going, watch out, or risky ---------------------------------------------------

@dataclass
class Verdict:
    level: str                  # "risk", "watch", "good", or "new" (too early to tell)
    bad: list                   # [(sign, numbers)], the serious ones first
    good: list


def is_stopped(v, now) -> bool:
    """Gone far longer than usual without buying (3x their usual gap, 21+ days), or
    60+ days for someone without a regular habit. No upper limit: a customer who
    stopped a year ago still matters if they owe money."""
    since = v.days_since(now)
    if since is None:
        return False
    if v.usual_gap:
        return since >= 21 and since >= 3 * max(v.usual_gap, 1)
    return since >= 60


def is_late(v, now) -> bool:
    """Owes 1,000+ and has not paid for 30+ days and twice their usual gap between payments."""
    since = v.days_since_payment(now)
    return (v.balance is not None and v.balance >= 1000 and since is not None
            and since >= max(30, 2 * (v.usual_pay_gap or 0)))


def assess(v, now, shop_margin=None) -> Verdict:
    """Is this customer worth the credit? Each sign carries the numbers behind it,
    so the owner can judge for himself. Money at stake decides how serious it is:
    5,000+ owed turns a warning about stopping or not paying into a risk."""
    risk, watch, good = [], [], []
    owes = v.balance is not None and v.balance >= 1000
    big = owes and v.balance >= 5000
    gone = is_stopped(v, now)
    if gone:
        (risk if big else watch).append(("stopped", {"days": v.days_since(now), "balance": v.balance if owes else 0}))
    if is_late(v, now):
        (risk if big else watch).append(("not_paying", {"days": v.days_since_payment(now), "gap": v.usual_pay_gap,
                                                        "never": v.last_payment is None, "balance": v.balance}))
    ratio, growth = v.pay_ratio, v.debt_growth
    if ratio is not None and growth is not None:
        if ratio < 0.5 and growth >= 10_000:
            risk.append(("takes_more", {"ratio": ratio, "growth": growth}))
        elif ratio < 0.8 and growth >= 5_000:
            watch.append(("takes_more", {"ratio": ratio, "growth": growth}))
        elif ratio >= 0.9:
            good.append(("pays_well", {"ratio": ratio, "growth": growth, "balance": v.balance}))
    # a lot owed counts less against someone who is bringing it down
    shrinking = growth is not None and growth <= -0.05 * max(v.balance or 0, 1)
    months = v.debt_months
    if months is not None and v.balance >= 5000:
        if months >= 6 and v.balance >= 20_000:
            (watch if shrinking else risk).append(("debt_months", {"months": months, "balance": v.balance}))
        elif months >= 3 and not shrinking:
            watch.append(("debt_months", {"months": months, "balance": v.balance}))
    change = v.activity_change
    if change is not None and not gone:
        if change <= -0.5:
            watch.append(("buys_less", {"change": change, "before": v.before_monthly, "now": v.recent_monthly}))
        elif change >= 0.3:
            good.append(("buys_more", {"change": change}))
    if v.margin is not None and v.life_total >= 10_000 and shop_margin:
        if v.margin < shop_margin / 2:
            watch.append(("low_margin", {"margin": v.margin, "shop": shop_margin}))
        elif v.margin >= shop_margin * 1.1:
            good.append(("good_margin", {"margin": v.margin, "shop": shop_margin}))
    bought = v.life_total + v.life_returns
    if v.life_returns >= 2000 and bought > 0 and v.life_returns / bought >= 0.10:
        watch.append(("returns", {"rate": v.life_returns / bought}))
    if v.balance is not None and abs(v.balance) < 1000 and v.life_total >= 10_000:
        good.append(("clear", {}))
    new = v.life_invoices < 5 or (v.first_buy is not None and (now - v.first_buy).days < 60)
    level = "risk" if risk else "watch" if watch else "new" if new else "good"
    return Verdict(level, risk + watch, good)


def shop_margin(cviews) -> float:
    total = sum(v.life_total for v in cviews)
    return sum(v.life_profit for v in cviews) / total if total > 0 else None


def rate(cviews, now) -> None:
    """Give every customer a verdict against the shop's own average margin."""
    cviews = list(cviews)
    margin = shop_margin(cviews)
    for v in cviews:
        v.verdict = assess(v, now, margin)


def by_level(cviews, level) -> list:
    """Customers with that verdict: the risky and the doubtful by money at stake,
    the good ones by what they earned the shop."""
    out = [v for v in cviews if v.verdict and v.verdict.level == level]
    if level in ("risk", "watch"):
        return sorted(out, key=lambda v: (-(v.balance or 0), -v.life_profit))
    return sorted(out, key=lambda v: -v.life_profit)
