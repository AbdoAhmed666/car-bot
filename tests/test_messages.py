from src import messages


def test_arabic_counting():
    assert messages.pieces(1) == "قطعة واحدة"
    assert messages.pieces(2) == "قطعتين"
    assert messages.pieces(5) == "5 قطع"
    assert messages.pieces(40) == "40 قطعة"
    assert messages.days_n(2) == "يومين"
    assert messages.invoices_n(3) == "3 فواتير"
    assert messages.invoices_n(12) == "12 فاتورة"
    assert messages.pieces(2.5) == "2.5 قطعة"


def test_split_keeps_messages_under_telegram_limit():
    text = "\n".join(f"سطر {n} " + "x" * 90 for n in range(200))
    parts = messages.split(text, limit=4000)
    assert all(len(p) <= 4000 for p in parts)
    assert "\n".join(parts) == text


def test_cover_text():
    assert messages.cover_text(0.4) == "يوم واحد"
    assert messages.cover_text(5) == "5 أيام"
    assert messages.cover_text(95) == "حوالي 3 شهور"
    assert messages.cover_text(400) == "أكتر من سنة"
    assert messages.cover_text(6750) == "أكتر من 18 سنة"


def test_short_names_and_money():
    assert messages.names(["أ", "ب", "ج", "د", "ه"]) == "أ، ب، ج و2 كمان"
    assert messages.names(["أ"]) == "أ"
    assert messages.short_money(184_600) == "185 ألف ج"
    assert messages.short_money(9_500) == "9,500 ج"
    assert messages.short_money(2_350_000) == "2.4 مليون ج"


def test_ago():
    from datetime import datetime
    now = datetime(2026, 9, 26)
    assert messages.ago_text(datetime(2026, 9, 20), now) == "من 6 أيام"
    assert messages.ago_text(datetime(2026, 9, 26, 13), datetime(2026, 9, 26, 23)) == "النهارده"
    assert messages.ago_text(datetime(2026, 9, 25, 23), datetime(2026, 9, 26, 1)) == "امبارح"
    assert messages.ago_text(datetime(2026, 5, 1), now) == "من 5 شهور"
    assert messages.ago_text(datetime(2025, 6, 1), now) == "من أكتر من سنة"
    assert messages.ago_text(None, now) == "متباعش خالص"


def test_page():
    lines = [f"• {n}" for n in range(25)]
    assert messages.page("h", lines, 0, "empty").splitlines()[-1] == "(صفحة 1 من 3)"
    assert messages.page("h", lines, 2, "empty").splitlines()[1] == "• 20"
    assert messages.page("h", [], 0, "empty") == "empty"


def test_account_lines():
    from datetime import datetime
    from src.analysis import CustomerView
    from src.shop import Customer
    now = datetime(2026, 9, 26, 18)
    v = CustomerView(customer=Customer(1, "معرض الصفا"), balance=150_000, last_payment=datetime(2026, 9, 23, 14),
                     last_payment_amount=15_000, usual_pay_gap=7)
    assert messages.account_lines(v, now) == ["💳 عليه: 150,000 ج",
                                              "آخر دفعة: 15,000 ج (من 3 أيام) · عادته يدفع كل 7 أيام"]
    assert messages.account_lines(CustomerView(customer=v.customer, balance=-1700), now) == ["💳 ليه عندك: 1,700 ج"]
    assert messages.account_lines(CustomerView(customer=v.customer, balance=0.3), now) == ["💳 حسابه خالص"]
    assert messages.account_lines(CustomerView(customer=v.customer, balance=5000), now)[1] == "مفيش دفعات متسجلة له"
    assert messages.account_lines(CustomerView(customer=v.customer), now) == []     # no balances in the snapshot


def test_sign_texts():
    assert messages.sign_text("pays_well", {"ratio": 1.2, "growth": -20_000}) == \
        "بيدفع أكتر من اللي بياخده، بيسدّد القديم: اللي عليه نزل 20 ألف ج في آخر 3 شهور"
    assert messages.sign_text("pays_well", {"ratio": 1.2, "growth": -20_000}, short=True) == "بيسدّد القديم"
    assert messages.sign_text("pays_well", {"ratio": 1.2, "growth": -20_000, "balance": -5000}) == \
        "بيدفع أكتر من اللي بياخده، وليه رصيد عندك"
    slow = {"weeks": 12.4, "norm": 6, "balance": 80_000, "shrinking": False}
    assert messages.sign_text("slow_collect", slow) == \
        "التحصيل بطيء: فلوسه بتقعد عنده حوالي 12 أسبوع والمفروض 6 أسابيع"
    assert messages.sign_text("slow_collect", {**slow, "shrinking": True}).endswith("، بس بيقلّل اللي عليه")
    assert messages.sign_text("slow_collect", slow, short=True) == "فلوسه بتقعد عنده 12 أسبوع"
    assert messages.sign_text("collects_ok", {**slow, "weeks": 3.2}) == "التحصيل كويس: فلوسه بترجع في حوالي 3 أسابيع"
    assert messages.sign_text("not_paying", {"days": 40, "gap": 7, "never": False, "balance": 9000}) == \
        "مدفعش من 40 يوم (عادته كل 7 أيام)"
    assert messages.sign_text("buys_less", {"change": -0.6, "before": 20_000, "now": 8_000}, short=True) == \
        "مشترياته قلّت 60%"


def test_customer_card_marks_items_no_longer_bought():
    from datetime import datetime
    from src.analysis import CustomerView
    from src.shop import Customer
    now = datetime(2026, 9, 26, 18)
    v = CustomerView(customer=Customer(1, "معرض الصفا"))
    card = messages.customer_card(v, [("فلتر زيت", 40, 2400, datetime(2026, 9, 20)),
                                      ("كويل", 6, 4200, datetime(2026, 4, 2))], now)
    assert "• فلتر زيت: 40 قطعة · 2,400 ج\n" in card
    assert "• كويل: 6 قطع · 4,200 ج (آخر مرة من 6 شهور)" in card


def test_who_took_it():
    assert messages.to_whom("مركز النجمة") == "لمركز النجمة"
    assert messages.to_whom("الزراني") == "للزراني"
    assert messages.to_whom("ABC") == "لـABC"
    assert messages.buyers_text([("الزراني", 2), ("علاء", 6.0)]) == "2 للزراني و6 لعلاء"
    assert messages.buyers_text([("أ", 3), ("ب", 2), ("ج", 1), ("د", 1)], limit=2) == "3 لأ، 2 لب وعميلين كمان"
    assert messages.buyers_text([("أ", 1.5)]) == "1.5 لأ"


def test_credit_cost_is_an_estimate():
    from src import analysis
    # 20% margin, all on credit, back in 60 days, money earning 2% a month elsewhere: 4 points less
    assert analysis.margin_after_credit(0.20, 1.0, 60, 2) == 0.20 - 0.04
    assert analysis.margin_after_credit(0.20, 0.5, 60, 2) == 0.20 - 0.02
    assert messages.credit_note(0.20, 1.0, 60, 2) == \
        "⏳ بعد تكلفة الآجل: حوالي 16% بدل 20% (تقدير: الفلوس بتقعد بره حوالي 9 أسابيع، ولو اشتغلت كانت هتكسب 2% في الشهر)"


def test_sales_details_page():
    groups = [{"name": f"عميل {n}", "invoices": [n], "total": 1000.0 - n, "profit": 100.0, "credit": 1000.0 - n,
               "cash": 0.0, "discount": 5.0 if n == 1 else 0.0,
               "items": {"كويل": {"qty": 2.0, "total": 900.0}, "فلتر": {"qty": 1.0, "total": 100.0}}}
              for n in range(1, 8)]
    first = messages.sales_page(groups, "السبت 26/9", 0)
    assert first.startswith("🧾 تفاصيل البيع · السبت 26/9") and first.count("👤 ") == messages.SALES_PAGE
    assert "👤 عميل 1: 999 ج · مكسب 100 ج (آجل)\nفاتورة 1\n• 2 كويل · 900 ج\n• 1 فلتر · 100 ج" in first
    assert "• خصم على الفاتورة: 5 ج" in first and first.endswith("(صفحة 1 من 2)")
    assert messages.sales_page(groups, "", 1).count("👤 ") == 2
    assert messages.sales_page([], "", 0) == "مفيش فواتير بيع"
    block = messages.buyers_block(groups)
    assert block[1] == "👥 مين اشترى (7):" and block[3] == "🛒 2 كويل، 1 فلتر"
    assert block[-1] == f"وعميلين كمان: دوس «{messages.BUTTON_SALES}»"
