"""The bot's Arabic messages.

Short on purpose: every message fits a phone screen and opens with what to
do. Long lists come 10 at a time behind buttons. Plain text (no Markdown),
so item names with symbols in them can't break the formatting.
"""
from .analysis import reorder_qty, weekly_value

WEEKDAYS = ["الاتنين", "التلات", "الأربع", "الخميس", "الجمعة", "السبت", "الحد"]

BUTTON_TODAY = "📊 النهارده"
BUTTON_WEEK = "📅 الأسبوع"
BUTTON_LOW = "⚠️ النواقص"
BUTTON_IDLE = "💤 الراكد"
BUTTON_CUSTOMERS = "👥 العملاء"
BUTTONS = [[BUTTON_TODAY, BUTTON_WEEK], [BUTTON_LOW, BUTTON_IDLE], [BUTTON_CUSTOMERS]]

PAGE = 10             # list lines per message
METHOD_NAMES = {"model": "موديل تعلّم آلي", "blend": "موديل تعلّم آلي مع متوسط 13 أسبوع",
                "average_13_weeks": "متوسط آخر 13 أسبوع", "croston": "طريقة Croston للبيع المتقطع"}


# --- words and numbers -----------------------------------------------------

def plural(n, one, two, few, many) -> str:
    """Arabic counting: 1 قطعة, 2 قطعتين, 3-10 قطع, 11+ قطعة."""
    whole = round(n)
    if abs(n - whole) > 0.01:
        return f"{n:,.1f} {many}"
    if whole == 1:
        return one
    if whole == 2:
        return two
    if 3 <= whole <= 10:
        return f"{whole} {few}"
    return f"{whole:,} {many}"


def pieces(n):
    return plural(n, "قطعة واحدة", "قطعتين", "قطع", "قطعة")


def invoices_n(n):
    return plural(n, "فاتورة واحدة", "فاتورتين", "فواتير", "فاتورة")


def items_n(n):
    return plural(n, "صنف واحد", "صنفين", "أصناف", "صنف")


def days_n(n):
    return plural(n, "يوم واحد", "يومين", "أيام", "يوم")


def months_n(n):
    return plural(n, "شهر", "شهرين", "شهور", "شهر")


def cover_text(days) -> str:
    """How long stock lasts, in days, months or years."""
    if days < 60:
        return days_n(max(round(days), 1))
    if days < 365:
        return f"حوالي {months_n(round(days / 30))}"
    return "أكتر من " + plural(int(days // 365), "سنة", "سنتين", "سنين", "سنة")


def ago_text(then, now) -> str:
    if then is None:
        return "متباعش خالص"
    days = (now.date() - then.date()).days
    if days <= 0:
        return "النهارده"
    if days == 1:
        return "امبارح"
    if days < 60:
        return f"من {days_n(days)}"
    if days < 365:
        return f"من {months_n(round(days / 30))}"
    return "من أكتر من سنة"


def last_sale_text(then, now) -> str:
    return f"آخر بيع {ago_text(then, now)}" if then else "متباعش خالص"


def money(x) -> str:
    return f"{x:,.0f} ج"


def short_money(x) -> str:
    """Round big amounts for headlines: 184,600 -> 185 ألف ج, 2,350,000 -> 2.4 مليون ج."""
    if abs(x) >= 1_000_000:
        return f"{x / 1_000_000:.1f} مليون ج"
    return f"{round(x / 1000):,} ألف ج" if abs(x) >= 10_000 else money(x)


def pct(part, whole) -> str:
    return f"{part / whole * 100:.0f}%" if whole else "-"


def day(d) -> str:
    return f"{d.day}/{d.month}"


def weekday(d) -> str:
    return f"{WEEKDAYS[d.weekday()]} {day(d)}"


def names(things, limit=3) -> str:
    """"أ، ب، ج و5 كمان"."""
    shown = "، ".join(things[:limit])
    return shown + (f" و{len(things) - limit} كمان" if len(things) > limit else "")


def stock_text(stock) -> str:
    if stock < 0:
        return f"{stock:,.0f} (بالسالب: غالبًا فيه فاتورة شراء متسجلتش)"
    if stock == 0:
        return "خلص"
    return pieces(stock)


def sales_line(t) -> list:
    if not t["count"] and not t["returns_count"]:
        return ["💵 مفيش فواتير بيع"]
    out = [f"💵 {invoices_n(t['count'])} · {money(t['total'])} · مكسب {money(t['profit'])} ({pct(t['profit'], t['total'])})"]
    if t["returns_count"]:
        out.append(f"↩️ مرتجع: {invoices_n(t['returns_count'])} بـ {money(t['returns_total'])}")
    return out


# --- one item ----------------------------------------------------------------

def item_card(v, window_days, low_days) -> str:
    i = v.item
    lines = [f"📦 {i.name}" + (f"  (كود {i.code})" if i.code else ""),
             f"الرصيد: {stock_text(i.stock)}"]
    if i.price:
        price = f"سعر البيع: {money(i.price)}"
        if i.cost:
            price += f" · التكلفة: {money(i.cost)} · مكسب القطعة: {money(i.price - i.cost)}"
        lines.append(price)
    demand_30 = v.forecast_30 if v.forecast_30 is not None else v.per_day * 30
    if v.sold > 0:
        pace = f" (حوالي {v.per_day * 7:,.1f} في الأسبوع)" if v.forecast_30 is None else ""
        lines.append(f"آخر {window_days} يوم: اتباع منه {pieces(v.sold)}{pace}")
    else:
        lines.append(f"مفيش بيع منه في آخر {window_days} يوم")
    if v.forecast_30 is not None and (v.sold > 0 or demand_30 >= 0.5):
        lines.append(f"📈 متوقع يتباع منه في الـ30 يوم الجايين: حوالي {pieces(round(demand_30))}"
                     if demand_30 >= 0.5 else "📈 مش متوقع يتباع منه حاجة الشهر الجاي")
    if demand_30 >= 0.5:
        cover = v.cover_days
        if cover is not None and i.stock > 0:
            warn = " ⚠️" if cover <= low_days else ""
            lines.append(f"الرصيد يكفي {cover_text(cover)}{warn}")
        elif i.stock <= 0:
            lines.append(f"⛔ خلص وعليه طلب. اطلب حوالي {pieces(reorder_qty(v))} تكفي شهر")
    lines.append(f"آخر بيع: {day(v.last_sale)}" if v.last_sale else "متباعش ولا مرة من ساعة ما البرنامج اشتغل")
    return "\n".join(lines)


def choose(query) -> str:
    return f"لقيت كذا حاجة قريبة من «{query}». اختار:"


def not_found(query) -> str:
    if not query:
        return "اكتبلي اسم صنف أو عميل، زي: فاضل كام من طلمبه باور اوبترا"
    return (f"مش لاقي صنف ولا عميل اسمه «{query}». جرّب جزء من الاسم أو الكود.\n"
            "وللتقارير دوس على الزراير تحت، أو اكتب مثلًا: تقرير الأسبوع")


# --- lists, 10 at a time ---------------------------------------------------

def low_line(v) -> str:
    order = f"اطلب {reorder_qty(v):,}"
    if v.item.stock < 0:
        return f"• {v.item.name}: رصيده بالسالب · {order}"
    if v.item.stock == 0:
        return f"• {v.item.name}: خلص · {order}"
    return f"• {v.item.name}: فاضل {v.item.stock:,.0f}، يكفي {cover_text(v.cover_days)} · {order}"


def low_header(needed, low_days) -> str:
    out = sum(1 for v in needed if v.item.stock <= 0)
    return (f"⚠️ النواقص: {items_n(len(needed))} ({out} خلص، {len(needed) - out} قرب يخلص في {days_n(low_days)})\n"
            f"بيجيبوا حوالي {short_money(sum(weekly_value(v) for v in needed))} في الأسبوع. "
            "الأهم الأول، والكمية تكفي شهر:")


def idle_line(v, now) -> str:
    return f"• {v.item.name}: {pieces(v.item.stock)} · {money(v.money)} · {last_sale_text(v.last_sale, now)}"


def idle_header(idle, idle_days) -> str:
    return (f"💤 الراكد: {items_n(len(idle))} متباعش من {days_n(idle_days)} · فيهم {short_money(sum(v.money for v in idle))}\n"
            "الأكبر فلوس الأول. اللي عدّى عليه سنة: خصم أو رجّعه للمورد.")


def slow_line(v) -> str:
    return f"• {v.item.name}: {pieces(v.item.stock)} تكفي {cover_text(v.cover_days)} · {money(v.money)}"


def slow_header(slow) -> str:
    return (f"🐢 البطيء: {items_n(len(slow))} بتتباع، بس رصيدها يكفي أكتر من 6 شهور · "
            f"فيهم {short_money(sum(v.money for v in slow))}\nمتطلبش منهم لحد ما الرصيد ينزل:")


def page(header, lines, number, empty) -> str:
    if not lines:
        return empty
    pages = (len(lines) + PAGE - 1) // PAGE
    number = min(max(number, 0), pages - 1)
    out = [header, *lines[number * PAGE:(number + 1) * PAGE]]
    if pages > 1:
        out.append(f"(صفحة {number + 1} من {pages})")
    return "\n".join(out)


# --- customers ---------------------------------------------------------------

def habit_text(gap) -> str:
    return "كل يوم" if gap <= 1.5 else f"كل {days_n(round(gap))}"


def account_lines(v, now) -> list:
    """What they owe and how they pay; nothing if the snapshot has no balances."""
    if v.balance is None:
        return []
    if v.balance >= 1:
        lines = [f"💳 عليه: {money(v.balance)}"]
    elif v.balance <= -1:
        lines = [f"💳 ليه عندك: {money(-v.balance)}"]
    else:
        lines = ["💳 حسابه خالص"]
    if v.last_payment:
        paid = f"آخر دفعة: {money(v.last_payment_amount)} ({ago_text(v.last_payment, now)})"
        if v.usual_pay_gap:
            paid += f" · عادته يدفع {habit_text(v.usual_pay_gap)}"
        lines.append(paid)
    elif v.balance >= 1:
        lines.append("مفيش دفعات متسجلة له")
    return lines


MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر",
          "نوفمبر", "ديسمبر"]
LEVELS = {"risk": "🔴 خطر: قلّل الآجل معاه وحصّل اللي عليه", "watch": "🟡 خلّي بالك منه",
          "good": "🟢 كمّل معاه", "new": "⚪ لسه جديد، بدري نحكم عليه"}


def month(d) -> str:
    return f"{MONTHS[d.month - 1]} {d.year}"


def sign_text(sign, d, short=False) -> str:
    """One reason behind a customer's verdict, with its numbers; `short` for lists."""
    if sign == "stopped":
        return f"بطّل يشتري من {days_n(d['days'])}"
    if sign == "not_paying":
        if d["never"]:
            return "مدفعش ولا مرة" if short else "مدفعش ولا مرة من ساعة ما بدأ يشتري"
        habit = f" (عادته كل {days_n(round(d['gap']))})" if d["gap"] and not short else ""
        return f"مدفعش من {days_n(d['days'])}{habit}"
    if sign == "takes_more":
        paid = f"دفع {d['ratio'] * 100:.0f}% بس من اللي أخده آخر 3 شهور"
        return paid if short else f"بياخد أكتر ما بيدفع: {paid}، ومديونيته زادت {short_money(d['growth'])}"
    if sign == "debt_months":
        months = months_n(round(d["months"]))
        return f"ده مشتريات {months}" if short else f"اللي عليه ({short_money(d['balance'])}) = مشترياته في {months}"
    if sign == "buys_less":
        less = f"مشترياته قلّت {-d['change'] * 100:.0f}%"
        return less if short else f"{less}: بقى بـ {short_money(d['now'])} في الشهر بدل {short_money(d['before'])}"
    if sign == "low_margin":
        margin = f"مكسبك منه {d['margin'] * 100:.0f}% بس"
        return margin if short else f"{margin} (متوسط المحل {d['shop'] * 100:.0f}%)"
    if sign == "returns":
        return f"مرتجعاته {d['rate'] * 100:.0f}%" if short else f"مرتجعاته كتير: {d['rate'] * 100:.0f}% من اللي اشتراه"
    if sign == "pays_well":
        if d["ratio"] > 1.05 and d.get("balance", 1) <= 0:
            return "بيدفع مقدّم" if short else "بيدفع أكتر من اللي بياخده، وليه رصيد عندك"
        if d["ratio"] > 1.05:
            down = f": اللي عليه نزل {short_money(-d['growth'])} في آخر 3 شهور" if d["growth"] < -1000 else ""
            return "بيسدّد القديم" if short else f"بيدفع أكتر من اللي بياخده، بيسدّد القديم{down}"
        return "بيدفع أول بأول" if short else f"بيدفع أول بأول: دفع {d['ratio'] * 100:.0f}% من اللي أخده آخر 3 شهور"
    if sign == "buys_more":
        return f"مشترياته زادت {d['change'] * 100:.0f}%" + ("" if short else " عن الأول")
    if sign == "good_margin":
        margin = f"مكسبك منه {d['margin'] * 100:.0f}%"
        return margin if short else f"{margin}، أعلى من متوسط المحل ({d['shop'] * 100:.0f}%)"
    if sign == "clear":
        return "حسابه نضيف"
    return sign


def verdict_lines(v) -> list:
    if not v.verdict:
        return []
    lines = [LEVELS[v.verdict.level]]
    lines += [f"⚠️ {sign_text(*b)}" for b in v.verdict.bad[:3]]
    if v.verdict.level in ("good", "new") or not v.verdict.bad:
        lines += [f"✅ {sign_text(*g)}" for g in v.verdict.good[:2]]
    return lines


def customer_card(v, top_items, now) -> str:
    """Everything about one customer: the verdict and why, what they owe, their whole
    history with the shop, lately against before, and what they buy most."""
    c = v.customer
    lines = [f"👤 {c.name}", *verdict_lines(v), ""]
    lines += account_lines(v, now)
    if v.life_invoices:
        lines.append(f"📊 من أول تعامل ({month(v.first_buy)}): {invoices_n(v.life_invoices)} · "
                     f"{money(v.life_total)} · مكسب {money(v.life_profit)} ({pct(v.life_profit, v.life_total)})")
    if v.before_monthly:
        lines.append(f"📈 آخر 3 شهور: بـ {short_money(v.recent_monthly)} في الشهر (قبلها {short_money(v.before_monthly)})")
    elif v.recent_monthly:
        lines.append(f"📈 آخر 3 شهور: بـ {short_money(v.recent_monthly)} في الشهر")
    if v.last_buy:
        habit = f" · عادته {habit_text(v.usual_gap)}" if v.usual_gap else ""
        lines.append(f"🕒 آخر شراء: {day(v.last_buy)} ({ago_text(v.last_buy, now)}){habit}")
    if top_items:
        lines.append("🛒 أكتر حاجات اشتراها من أول تعامل:")
        for name, qty, total, last in top_items:
            old = f" (آخر مرة {ago_text(last, now)})" if last and (now - last).days > 90 else ""
            lines.append(f"• {name}: {pieces(qty)} · {money(total)}{old}")
    return "\n".join(lines)


def cust_line(v) -> str:
    return f"• {v.customer.name}: مكسب {money(v.profit)} من {money(v.total)} · {invoices_n(v.invoices)}"


def stopped_line(v, now) -> str:
    return (f"• {v.customer.name}: مشتراش من {days_n(v.days_since(now))} (عادته {habit_text(v.usual_gap)}) · "
            f"كان بيشتري بـ {short_money(v.monthly)} في الشهر")


def debt_line(v, now) -> str:
    paid = f"آخر دفعة {ago_text(v.last_payment, now)}" if v.last_payment else "مفيش دفعات"
    return f"• {v.customer.name}: {money(v.balance)} · {paid}"


def late_line(v, now) -> str:
    if v.last_payment:
        paid = f"مدفعش من {days_n(v.days_since_payment(now))}"
        if v.usual_pay_gap:
            paid += f" (عادته {habit_text(v.usual_pay_gap)})"
    else:
        paid = "مفيش دفعات متسجلة"
    return f"• {v.customer.name}: عليه {money(v.balance)} · {paid}"


def verdict_line(v) -> str:
    """One customer in a list of risky / doubtful / good ones."""
    if v.verdict.level in ("risk", "watch"):
        owes = f" (عليه {short_money(v.balance)})" if v.balance and v.balance >= 1000 else ""
        return f"• {v.customer.name}{owes}: " + " · ".join(sign_text(*b, short=True) for b in v.verdict.bad[:2])
    why = f" · {sign_text(*v.verdict.good[0], short=True)}" if v.verdict.good else ""
    return f"• {v.customer.name}: مكسب {short_money(v.life_profit)} من أول تعامل{why}"


def customers_report(top, levels, new, now, window_days, owing=()) -> str:
    """levels: {"risk": [...], "watch": [...], "good": [...]} from analysis.by_level()."""
    out = ["👥 العملاء"]
    if top:
        out.append(f"💵 آخر {window_days} يوم: {plural(len(top), 'عميل واحد', 'عميلين', 'عملاء', 'عميل')} اشتروا بـ "
                   f"{short_money(sum(v.total for v in top))} · مكسب {short_money(sum(v.profit for v in top))}")
    if owing:
        out.append(f"💳 على العملاء: {short_money(sum(v.balance for v in owing))} "
                   f"({plural(len(owing), 'عميل واحد', 'عميلين', 'عملاء', 'عميل')})")
    out.append(f"🟢 كمّل معاهم {len(levels['good'])} · 🟡 خلّي بالك {len(levels['watch'])} · "
               f"🔴 خطر {len(levels['risk'])}")
    if levels["risk"]:
        out += ["", "🔴 ممكن يعملولك مشكلة:", *[verdict_line(v) for v in levels["risk"][:3]]]
    if top:
        out += ["", f"🏆 أكبر العملاء في المكسب (آخر {window_days} يوم):"]
        out += [f"{n}. {v.customer.name}: {money(v.profit)} من {money(v.total)}" for n, v in enumerate(top[:5], 1)]
    if new:
        out += ["", f"🆕 جداد ({len(new)}): " + names([v.customer.name for v in new])]
    return "\n".join(out)


# --- reports -----------------------------------------------------------------

def today(now, t, since_text) -> str:
    return "\n".join([f"📊 {weekday(now)} ({since_text})", *sales_line(t)])


def daily_update(now, t, ch, first_time, since_text) -> str:
    out = [f"📊 تحديث العصر · {weekday(now)} ({since_text})", *sales_line(t)]
    if first_time:
        out.append("📸 سجلت الأسعار والأرصدة النهارده. من بكره هقولك إيه اللي اتغير.")
        return "\n".join(out)
    if ch["price"]:
        out.append(f"🔄 أسعار اتغيرت ({len(ch['price'])}): "
                   + names([f"{i.name} من {old:,.0f} لـ {i.price:,.0f}" for i, old in ch["price"]]))
    if ch["arrived"]:
        out.append(f"📥 وصل بضاعة ({len(ch['arrived'])}): " + names([i.name for i, _ in ch["arrived"]]))
    if ch["ran_out"]:
        out.append(f"⛔ خلص ({len(ch['ran_out'])}): " + names([i.name for i in ch["ran_out"]]))
    if ch["new"]:
        out.append(f"🆕 أصناف جديدة ({len(ch['new'])}): " + names([i.name for i in ch["new"]]))
    if not (ch["price"] or ch["arrived"] or ch["ran_out"] or ch["new"]):
        out.append("مفيش تغيير في الأسعار أو الأرصدة من امبارح غير البيع.")
    return "\n".join(out)


def end_of_day(now, t, ran_out, low, losing, deleted, went_negative, item_names) -> str:
    out = [f"🌙 آخر اليوم · {weekday(now)}", *sales_line(t)]
    alerts = []
    if ran_out:
        alerts.append("• خلص النهارده: " + names([v.item.name for v in ran_out]))
    if low:
        alerts.append("• قرب يخلص: " + names([f"{v.item.name} ({cover_text(v.cover_days)})" for v in low]))
    if losing:
        alerts.append("• اتباع بخسارة: " + names(
            [f"{item_names.get(x['item'], x['item'])} (خسارة {money(-x['profit'])}، فاتورة {x['invoice']})" for x in losing]))
    if deleted:
        alerts.append(f"• اتمسح من الفواتير: {plural(len(deleted), 'سطر واحد', 'سطرين', 'سطور', 'سطر')} ("
                      + names([d["name"] for d in deleted]) + ")")
    if went_negative:
        alerts.append("• رصيده بقى بالسالب: " + names([i.name for i in went_negative]))
    out += ["", "⚠️ محتاج تبص عليه:", *alerts] if alerts else ["", "✅ مفيش حاجة تقلق النهارده."]
    return "\n".join(out)


def weekly(now, week_start, t, prev, top, needed, idle, slow, cheap, negative, top_customer=None,
           stopped=(), model=None, owed=None, risky=()) -> str:
    out = [f"📅 الأسبوع · {day(week_start)} لـ {day(now)}"]
    sales = f"💵 المبيعات: {money(t['net_total'])}"
    if prev["net_total"]:
        change = (t["net_total"] - prev["net_total"]) / prev["net_total"] * 100
        sales += f" ({change:+.0f}% عن اللي قبله)"
    out.append(sales)
    out.append(f"💰 المكسب: {money(t['net_profit'])} ({pct(t['net_profit'], t['net_total'])})"
               + (f" · آجل {pct(t['credit_total'], t['total'])}" if t["total"] else ""))
    if owed:
        out.append(f"💳 على العملاء: {short_money(owed)}")

    todo = []
    if needed:
        todo.append(f"اطلب الناقص، أهمهم: {names([v.item.name for v in needed])}. "
                    f"الـ{items_n(len(needed))} الناقصين بيجيبوا حوالي {short_money(sum(weekly_value(v) for v in needed))} في الأسبوع.")
    if risky:
        v = risky[0]
        why = f"عليه {short_money(v.balance or 0)}، {sign_text(*v.verdict.bad[0], short=True)}"
        todo.append(f"🔴 {v.customer.name} ممكن يعملك مشكلة ({why}). قلّل الآجل معاه وحصّل." if len(risky) == 1 else
                    f"🔴 {plural(len(risky), '', 'عميلين', 'عملاء', 'عميل')} ممكن يعملولك مشكلة وعليهم "
                    f"{short_money(sum(x.balance or 0 for x in risky))}، أكبرهم {v.customer.name} ({why}). "
                    "قلّل الآجل معاهم وحصّل.")
    if stopped:
        v = stopped[0]
        todo.append(f"{plural(len(stopped), 'عميل', 'عميلين', 'عملاء', 'عميل')} بطّلوا يشتروا، أهمهم {v.customer.name} "
                    f"(كان بيشتري بـ {short_money(v.monthly)} في الشهر). كلّمهم.")
    if idle:
        todo.append(f"فيه {short_money(sum(v.money for v in idle))} في بضاعة راكدة. "
                    f"ابدأ بـ {idle[0].item.name} ({money(idle[0].money)}).")
    if cheap:
        worst = cheap[0]
        price = f"(بيع {worst.price:,.0f} / تكلفة {worst.cost:,.0f})"
        todo.append(f"{worst.name} بيتباع بأقل من تكلفته {price}." if len(cheap) == 1 else
                    f"{items_n(len(cheap))} بتتباع بأقل من تكلفتها، أكبرهم {worst.name} {price}.")
    if negative and len(todo) < 3:
        todo.append(f"{negative[0].name} رصيده بالسالب: غالبًا فاتورة شراء متسجلتش." if len(negative) == 1 else
                    f"{items_n(len(negative))} رصيدهم بالسالب: غالبًا فواتير شراء متسجلتش.")
    if prev["net_total"] and t["net_total"] < prev["net_total"] * 0.8 and len(todo) < 3:
        todo.append("المبيعات نزلت أكتر من 20% عن الأسبوع اللي قبله.")
    if todo:
        out += ["", "⭐ أهم حاجات:"] + [f"{n}. {line}" for n, line in enumerate(todo[:3], 1)]

    out.append("")
    if top:
        name, qty, profit = top[0]
        out.append(f"🏆 أكتر صنف كسّب: {name} ({money(profit)} من {pieces(qty)})")
    if top_customer:
        out.append(f"👥 أكبر عميل: {top_customer[0]} ({money(top_customer[1])})")
    if model:
        method, error, plain_error = model
        out.append(f"{'🤖' if method in ('model', 'blend') else '📐'} التوقع بطريقة {METHOD_NAMES.get(method, method)}: "
                   f"أدق طريقة على مبيعات المحل، غلطها أقل من المتوسط العادي بـ {(1 - error / plain_error) * 100:.0f}%")
    out.append("للتفاصيل دوس على الزراير تحت.")
    return "\n".join(out)


def welcome(cfg) -> str:
    return ("أهلًا 👋 أنا مساعد المحل.\n"
            "اكتبلي اسم أي صنف أو عميل وأقولك كل حاجة عنه.\n"
            "مثال: فاضل كام من طلمبه باور اوبترا\n"
            "أو اسم عميل: تعرف عليه كام وآخر مرة دفع واشترى\n"
            "أو دوس على زرار من اللي تحت، أو اكتب: النهارده، تقرير الأسبوع، النواقص، "
            "الراكد، العملاء، المديونيات، مين ممكن يعملي مشكلة، التجار الكويسين\n\n"
            "وهبعتلك لوحدي:\n"
            f"• {cfg.daily_update:%H:%M} تحديث العصر\n"
            f"• {cfg.end_of_day:%H:%M} آخر اليوم، ولو فيه حاجة محتاجة تبص عليها\n"
            f"• كل {WEEKDAYS[cfg.weekly_day]} {cfg.weekly_time:%H:%M} تقرير الأسبوع\n\n"
            "وتقدر تطلب أي واحد فيهم دلوقتي: /daily أو /eod أو /weekly")


def refused(user_id) -> str:
    return (f"البوت ده خاص بالمحل.\nرقمك على تليجرام: {user_id}\n"
            "لو إنت من أصحاب المحل، ابعت الرقم ده للي مركّب البوت.")


def unavailable() -> str:
    return "مفيش داتا من البرنامج لسه. لما جهاز المحل يبعت أول تحديث هقدر أرد."


def updated_at(when, now) -> str:
    if when is None:
        return ""
    stamp = f"{when:%H:%M}" if when.date() == now.date() else f"{day(when)} {when:%H:%M}"
    return f"🕒 آخر تحديث من المحل: {stamp}"


def split(text, limit=4000) -> list:
    """Telegram allows 4096 characters per message; cut between lines."""
    parts, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    return parts + ([current] if current else [])
