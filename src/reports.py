"""Everything the bot can say: text plus the buttons under it.

Used by the chat logic (src/chat.py) and the CLI. Live, "today" means
everything entered since the last end-of-day report (tracked by document
id). With `as_of` set, the reports are computed as if it were that moment,
going by invoice dates: that is how they are tried on an old copy.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import analysis, messages
from .search import search
from .shop import Period


@dataclass
class Reply:
    text: str
    buttons: list = field(default_factory=list)    # rows of (label, callback data)


def _day_start(t):
    return t.replace(hour=0, minute=0, second=0, microsecond=0)


LIST_KINDS = ("low", "idle", "slow", "cust", "stopped", "debt", "late", "risk", "watch", "good")
CUSTOMER_LISTS = ("cust", "stopped", "debt", "late", "risk", "watch", "good")
CUSTOMER_WINDOW = 30        # days the customer numbers cover


class Reports:
    def __init__(self, shop, cfg, state, as_of=None):
        self.shop, self.cfg, self.state, self.as_of = shop, cfg, state, as_of

    def now(self):
        """Shop time (Cairo), whatever clock the machine runs on: the server runs on UTC."""
        return self.as_of or datetime.now(ZoneInfo(self.cfg.timezone)).replace(tzinfo=None)

    def business_day(self):
        """The day a late-night report belongs to: sales go on past midnight, so until
        6 in the morning it is still the day before."""
        return self.now() - timedelta(hours=6)

    def _stamp(self, text) -> str:
        stamp = messages.updated_at(self.shop.exported_at(), self.now())
        return f"{text}\n\n{stamp}" if stamp else text

    def _views(self):
        """All items with their sales over the velocity window."""
        now, days = self.now(), self.cfg.velocity_days
        items = self.shop.items()
        sales = self.shop.sales_by_item(now - timedelta(days=days), self.as_of)
        last = self.shop.last_sales(self.as_of)
        return items, analysis.views(items, sales, last, days, self.shop.forecasts(), self.shop.arrivals(self.as_of))

    def _today(self):
        """(period, label) for "today so far"."""
        if self.as_of:
            return Period(start=_day_start(self.as_of), end=self.as_of), "من أول اليوم"
        after = self.state.get("eod_ids")
        if after is None:
            return Period(start=_day_start(self.now())), "من أول اليوم"
        return Period(after=after), "من آخر تقرير آخر اليوم"

    def _totals(self, period):
        return analysis.totals(self.shop.invoices(period), self.shop.returns(period))

    def _customer_views(self):
        """Every customer, rated (analysis.rate)."""
        now, end = self.now(), self.as_of
        cutoff = now - timedelta(days=analysis.RECENT_DAYS)
        sales = self.shop.customer_sales
        cvs = analysis.customer_views(
            self.shop.customers(), sales(now - timedelta(days=CUSTOMER_WINDOW), end), sales(None, end),
            self.shop.purchase_days(end), self.shop.balances(end, since=cutoff),
            recent=sales(cutoff, end), before=sales(None, cutoff), now=now)
        analysis.rate(cvs.values(), now, self.cfg.collect_weeks * 7)
        return cvs

    def _collect(self, cvs=None):
        """About how many days money stays with traders across the shop."""
        return analysis.shop_collect_days((cvs or self._customer_views()).values())

    def _sales(self, period):
        """(who bought what, {item id: who took it}, the lines) for a report's period."""
        detail = self.shop.sales_detail(period)
        return (analysis.sales_by_customer(self.shop.invoices(period), detail),
                analysis.buyers_by_item(detail), detail)

    @staticmethod
    def _sales_button(period, groups):
        """The button to every customer and item of the report, by invoice ids."""
        ids = [i for g in groups for i in g["invoices"]]
        if not ids:
            return []
        return [[(messages.BUTTON_SALES, f"sales:{min(ids) - 1}:{max(ids)}")]]

    def _model_note(self):
        """(method, its error, the plain average's error) when a forecast is in use, for the weekly report."""
        meta = self.shop.meta()
        if meta.get("forecast_used") != "1" or "forecast_method" not in meta:
            return None
        return meta["forecast_method"], float(meta["forecast_wape"]), float(meta["forecast_plain_wape"])

    def _lists(self, vs):
        now = self.now()
        return {"low": analysis.needed(vs.values(), self.cfg.low_stock_days, self.cfg.min_sold),
                "idle": analysis.idle(vs.values(), now, self.cfg.idle_days),
                "slow": analysis.slow_movers(vs.values(), new_since=now - timedelta(days=self.cfg.velocity_days))}

    # --- answers ---------------------------------------------------------------

    def ask(self, text) -> Reply:
        """An item or a customer, whichever the text fits better."""
        items, vs = self._views()
        cvs = self._customer_views()
        fi = search(text, items, popularity={i: v.sold for i, v in vs.items()})
        fc = search(text, [v.customer for v in cvs.values()], popularity={c: v.total for c, v in cvs.items()})
        has_i, has_c = bool(fi.item or fi.choices), bool(fc.item or fc.choices)

        if fc.hinted and has_c:                     # "حساب ..."، "... عليه كام"
            fi, has_i = type(fi)(choices=[], query=fi.query), False
        if fi.item and (not has_c or fi.score >= fc.score + 3):
            return self.item(fi.item.id)
        if fc.item and (not has_i or fc.score >= fi.score + 3):
            return self.customer(fc.item.id)
        buttons = []
        sides = [(fi.score, [[(i.name[:60], f"item:{i.id}")] for i in (fi.choices or [fi.item] if has_i else [])]),
                 (fc.score, [[("👤 " + c.name[:57], f"customer:{c.id}")] for c in (fc.choices or [fc.item] if has_c else [])])]
        for _, rows in sorted(sides, key=lambda s: -s[0]):
            buttons += rows
        if buttons:
            return Reply(messages.choose(fi.query or fc.query), buttons[:8])
        return Reply(messages.not_found(fi.query))

    def item(self, item_id) -> Reply:
        _, vs = self._views()
        if item_id not in vs:
            return Reply("الصنف ده مش موجود دلوقتي.")
        now = self.now()
        history = self.shop.item_history(item_id, now - timedelta(days=self.cfg.velocity_days), self.as_of, limit=4)
        return Reply(self._stamp(messages.item_card(vs[item_id], self.cfg.velocity_days, self.cfg.low_stock_days,
                                                    history, now)))

    def customer(self, customer_id) -> Reply:
        cvs = self._customer_views()
        if customer_id not in cvs:
            return Reply("العميل ده مش موجود.")
        v, now = cvs[customer_id], self.now()
        top = self.shop.customer_items(customer_id, None, self.as_of, limit=5)
        return Reply(self._stamp(messages.customer_card(v, top, now, self.cfg.collect_weeks,
                                                        self.cfg.money_cost_monthly)))

    def customers(self) -> Reply:
        cvs, now = self._customer_views(), self.now()
        top = analysis.top_customers(cvs.values())
        levels = {level: analysis.by_level(cvs.values(), level) for level in ("risk", "watch", "good")}
        stopped = analysis.stopped_buying(cvs.values(), now)
        new = analysis.new_customers(cvs.values(), now)
        owing = analysis.owing(cvs.values())
        late = analysis.late_payers(cvs.values(), now)
        rows = [[(f"🔴 خطر ({len(levels['risk'])})", "open:risk"), (f"🟡 خلّي بالك ({len(levels['watch'])})", "open:watch")],
                [(f"🟢 كمّل معاهم ({len(levels['good'])})", "open:good"), ("🏆 بالمكسب", "open:cust")],
                [(f"💳 المديونيات ({len(owing)})", "open:debt")] if owing else [],
                ([(f"⏰ متأخرين في الدفع ({len(late)})", "open:late")] if late else [])
                + ([(f"بطّلوا يشتروا ({len(stopped)})", "open:stopped")] if stopped else [])]
        text = messages.customers_report(top, levels, new, now, CUSTOMER_WINDOW, owing,
                                         self._collect(cvs), self.cfg.collect_weeks)
        return Reply(self._stamp(text), [row for row in rows if row])

    def today(self) -> Reply:
        period, label = self._today()
        groups, _, _ = self._sales(period)
        text = messages.today(self.now(), self._totals(period), label, groups, self._collect(),
                              self.cfg.money_cost_monthly)
        return Reply(self._stamp(text), self._sales_button(period, groups))

    def sales_page(self, after, upto, number=0) -> Reply:
        """Every customer and item of the invoices after `after` up to `upto`, a page at a time."""
        period = Period(after={"sal": after}, upto={"sal": upto})
        groups, _, _ = self._sales(period)
        dates = [d for d in (x["date"] for x in self.shop.invoices(period)) if d]
        title = ""
        if dates:
            first, last = min(dates), max(dates)
            title = messages.weekday(first) if first.date() == last.date() else f"{messages.day(first)} لـ {messages.day(last)}"
        text = messages.sales_page(groups, title, number)
        pages = max(1, (len(groups) + messages.SALES_PAGE - 1) // messages.SALES_PAGE)
        number = min(max(number, 0), pages - 1)
        nav = []
        if number < pages - 1:
            nav.append(("التالي ◀", f"sales:{after}:{upto}:{number + 1}"))
        if number > 0:
            nav.append(("▶ السابق", f"sales:{after}:{upto}:{number - 1}"))
        return Reply(self._stamp(text), [nav] if nav else [])

    def list_page(self, kind, number=0) -> Reply:
        """One page of a long list, with buttons to turn pages."""
        now, days = self.now(), self.cfg
        if kind in CUSTOMER_LISTS:
            cvs = self._customer_views()
            if kind in ("risk", "watch", "good"):
                views = analysis.by_level(cvs.values(), kind)
                header = {"risk": "🔴 ممكن يعملولك مشكلة (الأكبر فلوس الأول):",
                          "watch": "🟡 خلّي بالك منهم (الأكبر فلوس الأول):",
                          "good": "🟢 كمّل معاهم (الأكتر مكسب الأول):"}[kind]
                empty = {"risk": "✅ مفيش عميل خطر دلوقتي", "watch": "✅ مفيش عميل محتاج تاخد بالك منه",
                         "good": "مفيش عملاء كفاية لسه للحكم"}[kind]
                text = messages.page(header, [messages.verdict_line(v) for v in views], number, empty)
            elif kind == "debt":
                views = analysis.owing(cvs.values())
                text = messages.page(f"💳 المديونيات (الأكبر الأول) · الإجمالي {messages.short_money(sum(v.balance for v in views))}:",
                                     [messages.debt_line(v, now) for v in views], number, "✅ مفيش عميل عليه فلوس")
            elif kind == "late":
                views = analysis.late_payers(cvs.values(), now)
                text = messages.page("⏰ متأخرين في الدفع (الأكبر الأول):",
                                     [messages.late_line(v, now) for v in views], number,
                                     "✅ مفيش عميل متأخر في الدفع")
            elif kind == "cust":
                views = analysis.top_customers(cvs.values())
                text = messages.page(f"👥 العملاء بالمكسب (آخر {CUSTOMER_WINDOW} يوم):",
                                     [messages.cust_line(v) for v in views], number, "مفيش مبيعات للعملاء")
            else:
                views = analysis.stopped_buying(cvs.values(), now)
                text = messages.page("⚠️ عملاء بطّلوا يشتروا (الأكبر الأول):",
                                     [messages.stopped_line(v, now) for v in views], number,
                                     "✅ مفيش عميل متأخر عن عادته")
            return self._paged(kind, number, len(views), text)
        _, vs = self._views()
        views = self._lists(vs)[kind]
        if kind == "low":
            text = messages.page(messages.low_header(views, days.low_stock_days),
                                 [messages.low_line(v) for v in views], number,
                                 f"✅ مفيش صنف بيتباع ورصيده يكفي أقل من {messages.days_n(days.low_stock_days)}")
        elif kind == "idle":
            text = messages.page(messages.idle_header(views, days.idle_days),
                                 [messages.idle_line(v, now) for v in views], number,
                                 f"✅ مفيش بضاعة راكدة من {messages.days_n(days.idle_days)}")
        else:
            text = messages.page(messages.slow_header(views), [messages.slow_line(v) for v in views], number,
                                 "✅ مفيش أصناف رصيدها أكبر من اللازم")
        return self._paged(kind, number, len(views), text)

    def _paged(self, kind, number, count, text) -> Reply:
        pages = max(1, (count + messages.PAGE - 1) // messages.PAGE)
        number = min(max(number, 0), pages - 1)
        nav = []
        if number < pages - 1:
            nav.append(("التالي ◀", f"list:{kind}:{number + 1}"))
        if number > 0:
            nav.append(("▶ السابق", f"list:{kind}:{number - 1}"))
        return Reply(self._stamp(text), [nav] if nav else [])

    def low(self) -> Reply:
        return self.list_page("low")

    def idle(self) -> Reply:
        return self.list_page("idle")

    # --- scheduled reports -----------------------------------------------------

    def daily_update(self, save=True) -> Reply:
        """After Asr: sales so far today, and what changed in prices and stock since yesterday."""
        period, label = self._today()
        items = self.shop.items()
        snapshot = self.state.snapshot()
        groups, buyers, _ = self._sales(period)
        text = messages.daily_update(self.now(), self._totals(period), analysis.changes(snapshot, items),
                                     first_time=not snapshot, since_text=label, groups=groups, buyers=buyers,
                                     collect=self._collect(), money_cost=self.cfg.money_cost_monthly)
        if save:
            self.state.save_snapshot(items)
        return Reply(self._stamp(text), self._sales_button(period, groups))

    def end_of_day(self, save=True) -> Reply:
        """The day's sales, and only the alerts that matter."""
        if self.as_of:
            period, ids = self._today()[0], None
        else:
            ids = self.shop.last_ids()          # fixed first, so nothing slips between query and save
            after = self.state.get("eod_ids")
            period = Period(after=after, upto=ids) if after else Period(start=_day_start(self.now()))
        _, vs = self._views()
        groups, buyers, lines = self._sales(period)
        sold_today = {line["item_id"] for line in lines}
        low_days, min_sold = self.cfg.low_stock_days, self.cfg.min_sold

        went_negative = [vs[i].item for i in sold_today if i in vs and vs[i].item.stock < 0]
        ran_out = [vs[i] for i in sold_today if i in vs and vs[i].item.stock == 0 and vs[i].sold >= min_sold]
        low = [vs[i] for i in sold_today if i in vs and vs[i].item.stock > 0 and vs[i].sold >= min_sold
               and vs[i].cover_days is not None and vs[i].cover_days <= low_days]
        text = messages.end_of_day(
            self.business_day(), self._totals(period),
            ran_out=sorted(ran_out, key=lambda v: -analysis.weekly_value(v)),
            low=sorted(low, key=lambda v: v.cover_days),
            losing=analysis.losing_lines(lines),
            deleted=self.shop.deleted_lines(period),
            went_negative=went_negative,
            groups=groups, buyers=buyers, collect=self._collect(), money_cost=self.cfg.money_cost_monthly)
        if save and ids is not None:
            self.state.set("eod_ids", ids)
        return Reply(self._stamp(text), self._sales_button(period, groups))

    def weekly(self) -> Reply:
        now = self.now()
        week_start = _day_start(now - timedelta(days=6))
        prev_start = week_start - timedelta(days=7)
        this_week = self._totals(Period(start=week_start, end=self.as_of))
        prev_week = self._totals(Period(start=prev_start, end=week_start))

        items, vs = self._views()
        lists = self._lists(vs)
        week_sales = self.shop.sales_by_item(week_start, self.as_of)
        item_names = {i.id: i.name for i in items}
        top = sorted(((item_names.get(i, str(i)), s.qty, s.profit) for i, s in week_sales.items() if s.profit > 0),
                     key=lambda x: -x[2])[:3]
        cvs = self._customer_views()
        risky = analysis.by_level(cvs.values(), "risk")
        week_customers = self.shop.customer_sales(week_start, self.as_of)
        best = max(((cvs[c].customer.name, s["profit"]) for c, s in week_customers.items() if c in cvs),
                   key=lambda x: x[1], default=None)
        text = messages.weekly(now, week_start, this_week, prev_week, top, lists["low"], lists["idle"],
                               lists["slow"], analysis.below_cost(items), analysis.negative_stock(items),
                               top_customer=best, stopped=analysis.stopped_buying(cvs.values(), now),
                               model=self._model_note(),
                               owed=sum(v.balance for v in analysis.owing(cvs.values())), risky=risky,
                               collect=self._collect(cvs), money_cost=self.cfg.money_cost_monthly)
        buttons = [[(f"{messages.BUTTON_LOW} ({len(lists['low'])})", "open:low"),
                    (f"{messages.BUTTON_IDLE} ({len(lists['idle'])})", "open:idle")],
                   [(f"🐢 البطيء ({len(lists['slow'])})", "open:slow")]]
        if risky:
            buttons[1].append((f"🔴 عملاء خطر ({len(risky)})", "open:risk"))
        return Reply(self._stamp(text), buttons)
