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
    assert messages.sign_text("debt_months", {"months": 4.2, "balance": 80_000}) == \
        "اللي عليه (80 ألف ج) = مشترياته في 4 شهور"
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
