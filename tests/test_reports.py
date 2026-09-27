"""The reports on the fake shop (tests/fake_shop.py), read from its snapshot."""
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime

import pytest

from src import messages
from src.reports import Reports
from src.shop import Shop
from src.state import State

AS_OF = datetime(2026, 9, 26, 23, 30)       # fake_shop.ANCHOR, late evening


@pytest.fixture
def reports(shop_cfg):
    return Reports(Shop(shop_cfg), shop_cfg, State(shop_cfg.state_path), as_of=AS_OF)


@pytest.fixture
def own_snapshot(shop_cfg, tmp_path):
    """A private copy of the fake snapshot, for tests that change it."""
    path = tmp_path / "own.db"
    shutil.copy(shop_cfg.snapshot_path, path)
    return replace(shop_cfg, snapshot_path=path)


def test_check(shop_cfg):
    r = Shop(shop_cfg).check()
    assert r["items"] == 35 and r["invoices"] > 1000 and r["customers"] == 13
    assert r["exported_at"] == datetime(2026, 9, 26, 18, 0)


def test_ask_one_item(reports):
    r = reports.ask("فاضل كام من طلمبة باور أوبترا؟")
    assert r.buttons == []
    assert r.text.startswith("📦 طلمبه باور اوبترا")
    assert "الرصيد: 4 قطع" in r.text and "مكسب القطعة" in r.text and "آخر بيع" in r.text
    assert r.text.endswith("🕒 آخر تحديث من المحل: 18:00")


def test_ask_several(reports):
    r = reports.ask("طلمبه باور")
    assert len(r.buttons) >= 5 and "اختار" in r.text
    assert all(len(row) == 1 and "طلمبه باور" in row[0][0] and row[0][1].startswith("item:") for row in r.buttons)


def test_ask_out_of_stock(reports):
    text = reports.ask("زيت فتيس 4 سرعات").text
    assert "الرصيد: خلص" in text and "اطلب" in text


def test_ask_never_sold_and_deleted(reports):
    assert "متباعش ولا مرة" in reports.ask("خرطوم تكيف سيراتو 2015").text
    assert reports.ask("صنف قديم ممسوح").text.startswith("مش لاقي")


def test_item_by_id(reports):
    assert reports.item(6).text.startswith("📦 طلمبه باور اوبترا")


def test_low(reports):
    text = reports.low().text
    assert text.startswith("⚠️ النواقص:")
    for name in ["زيت فتيس 4 سرعات", "زيت فتيس 6 سرعات", "كويل لانوس", "فلتر تكييف نيوالينترا",
                 "ماستر فرامل عمومى لانوس"]:
        assert name in text
    assert "بلي عجل امامي لانوس HSC" not in text          # 148 in stock


def test_idle_and_slow(reports):
    lines = reports.idle().text.splitlines()
    assert lines[0].startswith("💤 الراكد: 6 أصناف")
    money = [float(line.split(" · ")[1].split(" ج")[0].replace(",", "")) for line in lines if line.startswith("• ")]
    assert len(money) == 6 and money == sorted(money, reverse=True)              # the most money first
    assert any(line.startswith("• تيش ميزان خلفي بوما CTR") for line in lines)   # padding gone
    assert any(line.startswith("• خرطوم تكيف سيراتو 2015: 10 قطع · ") and line.endswith("· متباعش خالص")
               for line in lines)
    assert "سيلكون المانى فكتور رانز" in reports.list_page("slow").text


def test_paging(reports, monkeypatch):
    monkeypatch.setattr(messages, "PAGE", 2)
    first = reports.list_page("idle", 0)
    assert "(صفحة 1 من 3)" in first.text and first.buttons == [[("التالي ◀", "list:idle:1")]]
    middle = reports.list_page("idle", 1)
    assert middle.buttons == [[("التالي ◀", "list:idle:2"), ("▶ السابق", "list:idle:0")]]
    last = reports.list_page("idle", 9)                   # past the end: the last page
    assert "(صفحة 3 من 3)" in last.text and last.buttons == [[("▶ السابق", "list:idle:1")]]


def test_end_of_day(reports):
    text = reports.end_of_day(save=False).text
    assert text.startswith("🌙 آخر اليوم · السبت 26/9")
    assert "↩️ مرتجع" in text
    alerts = text.split("⚠️ محتاج تبص عليه:")[1]
    assert "كويل لانوس" in alerts.split("• قرب يخلص")[0]           # ran out today
    assert "• اتباع بخسارة: مشترك ريداتير كياسول بالغطاء" in alerts
    assert "فلتر زيت تويوتا" in alerts.split("• اتمسح من الفواتير")[1]


def test_weekly_is_short_and_leads_with_actions(reports):
    reply = reports.weekly()
    text = reply.text
    assert text.startswith("📅 الأسبوع · 20/9 لـ 26/9")
    assert len(text.splitlines()) <= 20
    todo = text.split("⭐ أهم حاجات:")[1]
    assert "1. اطلب الناقص" in todo
    assert "2. 🔴" in todo and "ممكن يعملولك مشكلة" in todo and "قلّل الآجل" in todo
    assert "3. عميلين بطّلوا يشتروا، أهمهم ورشة الأمانة" in todo
    assert "💳 على العملاء:" in text
    assert "🏆 أكتر صنف كسّب" in text and "👥 أكبر عميل: مركز النجمة" in text
    data = [d for row in reply.buttons for _, d in row]
    assert data == ["open:low", "open:idle", "open:slow", "open:risk"]


def test_live_end_of_day_continues_from_last_report(own_snapshot):
    """Live, each end-of-day report covers what was entered since the previous one."""
    reports = Reports(Shop(own_snapshot), own_snapshot, State(own_snapshot.state_path))
    reports.end_of_day()                                   # first run: remembers where it stopped
    assert "مفيش فواتير بيع" in reports.end_of_day().text  # nothing new since

    # a new invoice arrives with the next snapshot: entered now, dated two days ahead
    db = sqlite3.connect(own_snapshot.snapshot_path)
    db.execute("INSERT INTO invoices VALUES (999999, datetime('now', '+2 days'), 3, 1234, 300, 0, 1, 0)")
    db.commit()
    db.close()
    text = reports.end_of_day().text
    assert "فاتورة واحدة" in text and "1,234 ج" in text
    assert "مفيش فواتير بيع" in reports.end_of_day().text


def test_daily_update_snapshot(shop_cfg):
    state = State(shop_cfg.state_path)
    reports = Reports(Shop(shop_cfg), shop_cfg, state)
    assert "📸" in reports.daily_update().text             # first time: only records
    assert "مفيش تغيير" in reports.daily_update().text

    snap = state.snapshot()
    snap[6]["price"] = 2000                                # as if the price was different yesterday
    snap[1]["stock"] = 2
    state.save_snapshot([type("I", (), {"id": k, **v})() for k, v in snap.items()])
    text = reports.daily_update().text
    assert "🔄 أسعار اتغيرت (1): طلمبه باور اوبترا من 2,000 لـ" in text
    assert "📥 وصل بضاعة (1): فلتر تكييف نيوالينترا" in text


# --- customers -----------------------------------------------------------------

def _lifetime_items(name, until):
    """(item name, total) this customer bought most, straight from the fake shop's rows."""
    from collections import Counter
    from tests import fake_shop
    src = fake_shop.source_rows()
    cid = next(c["id_cust"] for c in src["customers"] if " ".join(c["Aname"].split()) == name)
    invoices = {i["id_sal"] for i in src["invoices"] if i["id_cust"] == cid and i["pdate"] < until}
    items = {i["id_item"]: " ".join(i["ARname"].split()) for i in src["items"]}
    totals = Counter()
    for line in src["invoice_lines"]:
        if line["id_sal"] in invoices:
            totals[items[line["id_item"]]] += line["total_item"]
    return totals.most_common(5)


def test_ask_customer(reports):
    text = reports.ask("مركز النجمة").text
    assert text.startswith("👤 مركز النجمة")
    assert "🕒 آخر شراء: 26/9 (النهارده) · عادته كل يوم" in text
    assert "📊 من أول تعامل (نوفمبر 2025):" in text and "📈 آخر 3 شهور:" in text
    # what they bought most over their whole history, not lately
    shown = text.split("🛒 أكتر حاجات اشتراها من أول تعامل:")[1].split("\n\n")[0].strip().splitlines()
    expected = _lifetime_items("مركز النجمة", AS_OF)
    assert [line[2:].split(":")[0] for line in shown] == [name for name, _ in expected]
    assert f"· {expected[0][1]:,.0f} ج" in shown[0]


def test_customer_who_stopped(reports):
    text = reports.ask("حساب ورشة الأمانة").text
    assert text.startswith("👤 ورشة الأمانة\n🔴 خطر")               # stopped buying, and owes money
    assert "⚠️ بطّل يشتري من" in text and "⚠️ مدفعش من" in text


def test_customer_and_item_choices(reports):
    r = reports.ask("ورشة")
    assert [d for row in r.buttons for _, d in row] == ["customer:4", "customer:7"]
    assert reports.ask("كويل").text.startswith("📦 كويل لانوس")           # items still win for items


def _profits(lines):
    return [float(line.split("مكسب ")[-1].split(" ج")[0].replace(",", "")) if "مكسب " in line
            else float(line.split(": ")[1].split(" ج")[0].replace(",", "")) for line in lines]


def test_customers_report(reports):
    reply = reports.customers()
    text = reply.text
    top = [line for line in text.splitlines() if line[:2] in ("1.", "2.", "3.", "4.", "5.")]
    assert len(top) == 5 and _profits(top) == sorted(_profits(top), reverse=True)
    assert "🆕 جداد (1): مركز الهدى" in text
    assert "نقــــدى" not in text and "نقدى" not in text and "مورد قطع غيار" not in text   # walk-in, supplier
    assert "💳 على العملاء:" in text and "🟢 كمّل معاهم" in text and "🔴 خطر" in text
    risky = text.split("🔴 ممكن يعملولك مشكلة:")[1].split("\n\n")[0]
    assert "مؤسسة التوفيق (عليه" in risky and "مدفعش من" in risky
    assert [d for row in reply.buttons for _, d in row] == [
        "open:risk", "open:watch", "open:good", "open:cust", "open:debt", "open:late", "open:stopped"]


def test_customer_lists(reports):
    lines = [x for x in reports.list_page("cust").text.splitlines() if x.startswith("• ")]
    assert len(lines) == 9 and _profits(lines) == sorted(_profits(lines), reverse=True)
    lines = reports.list_page("stopped").text.splitlines()
    assert lines[1].startswith("• ورشة الأمانة: مشتراش من 40 يوم")


def _owed(source, name):
    """What the customer owes, straight from the ledger rows the export reads."""
    account = next(c["id_account"] for c in source["customers"] if " ".join(c["Aname"].split()) == name)
    return sum(r["debt"] - r["credit"] for r in source["ledger"] if r["id_Account"] == account)


def test_debts(reports):
    from tests import fake_shop
    source = fake_shop.source_rows()
    lines = [x for x in reports.list_page("debt").text.splitlines() if x.startswith("• ")]
    amounts = [float(x.split(": ")[1].split(" ج")[0].replace(",", "")) for x in lines]
    assert amounts == sorted(amounts, reverse=True) and len(lines) >= 3
    top = lines[0].split("• ")[1].split(":")[0]
    assert amounts[0] == round(_owed(source, top))
    assert "نقــــدى" not in "".join(lines)

    lines = reports.list_page("late").text.splitlines()
    assert lines[1].startswith("• مؤسسة التوفيق: عليه") and "(عادته كل 10 أيام)" in lines[1]


def test_customer_card_shows_what_they_owe(reports):
    from tests import fake_shop
    text = reports.ask("مؤسسة التوفيق عليه كام").text
    assert text.startswith("👤 مؤسسة التوفيق")
    owed = round(_owed(fake_shop.source_rows(), "مؤسسة التوفيق"))
    assert f"💳 عليه: {owed:,} ج" in text
    assert "آخر دفعة:" in text and "⚠️ مدفعش من" in text
    text = reports.ask("مركز النجمة").text
    assert "💳 عليه:" in text and "آخر دفعة:" in text and "مدفعش" not in text


def test_verdict_lists(reports):
    risky = [x for x in reports.list_page("risk").text.splitlines() if x.startswith("• ")]
    owed = [float(x.split("(عليه ")[1].split(" ألف")[0]) for x in risky]
    assert owed == sorted(owed, reverse=True) and any("مؤسسة التوفيق" in x for x in risky)
    good = [x for x in reports.list_page("good").text.splitlines() if x.startswith("• ")]
    profits = [float(x.split("مكسب ")[1].split(" ألف")[0]) for x in good]
    assert profits == sorted(profits, reverse=True)
    names = {x[2:].split(" (")[0].split(":")[0] for x in risky + good}
    watch = reports.list_page("watch").text
    assert not any(n in watch for n in names)                        # each customer in one list only


def test_account_activity_matches_the_ledger(reports):
    """What they owed 90 days ago, took on credit and paid since: straight from the ledger rows."""
    from datetime import timedelta
    from tests import fake_shop
    src, since = fake_shop.source_rows(), AS_OF - timedelta(days=90)
    got = reports.shop.balances(AS_OF, since=since)
    for c in src["customers"]:
        rows = [r for r in src["ledger"] if r["id_Account"] == c["id_account"] and r["pdate"] < AS_OF]
        if c["id_cust"] not in got:
            assert not rows
            continue
        b = got[c["id_cust"]]
        assert b["before"] == pytest.approx(sum(r["debt"] - r["credit"] for r in rows if r["pdate"] < since))
        assert b["bought"] == pytest.approx(sum(r["debt"] for r in rows if r["pdate"] >= since))
        assert b["paid"] == pytest.approx(sum(r["credit"] for r in rows if r["pdate"] >= since and r["id_CashCome"]))
    assert reports.shop.first_invoice() == min(i["pdate"] for i in src["invoices"]).replace(microsecond=0)
