"""What the bot answers, without Telegram."""
from src import messages
from src.chat import Chat
from src.reports import Reply
from src.shop import ShopUnavailable


class FakeReports:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if self.fail:
            raise ShopUnavailable("no snapshot")
        return Reply(f"{name} report", [[("b", "x")]] if name == "weekly" else [])

    def today(self):
        return self._call("today")

    def low(self):
        return self._call("low")

    def idle(self):
        return self._call("idle")

    def weekly(self):
        return self._call("weekly")

    def list_page(self, kind, number=0):
        return self._call("list", kind, number)

    def item(self, item_id):
        return self._call("item", item_id)

    def daily_update(self, save=True):
        return self._call("daily", save)

    def end_of_day(self, save=True):
        return self._call("eod", save)

    def ask(self, text):
        self.calls.append(("ask", text))
        if self.fail:
            raise ShopUnavailable("no snapshot")
        if text == "طلمبه باور":
            return Reply("choose", [[("طلمبه باور اوبترا", "item:6")], [("طلمبه باور لانوس", "item:7")]])
        return Reply(f"card for {text}")


def chat(cfg, fail=False):
    reports = FakeReports(fail)
    return Chat(reports, cfg), reports


def test_stranger_only_gets_their_id(cfg):
    c, reports = chat(cfg)
    (out,) = c.on_text(999, "فاضل كام من طلمبه باور اوبترا")
    assert "999" in out.text and "خاص" in out.text and reports.calls == []
    assert c.on_button(999, "item:6") == [] and reports.calls == []


def test_start_shows_keyboard_and_schedule(cfg):
    c, _ = chat(cfg)
    (out,) = c.on_text(111, "/start")
    assert out.keyboard and "16:30" in out.text and "الخميس" in out.text


def test_main_buttons(cfg):
    c, reports = chat(cfg)
    assert c.on_text(111, messages.BUTTON_TODAY)[0].text == "today report"
    (out,) = c.on_text(111, messages.BUTTON_WEEK)
    assert out.text == "weekly report" and out.buttons == [[("b", "x")]]
    c.on_text(111, messages.BUTTON_LOW)
    c.on_text(111, messages.BUTTON_IDLE)
    assert reports.calls == [("today",), ("weekly",), ("low",), ("idle",)]


def test_question_and_choices(cfg):
    c, _ = chat(cfg)
    assert c.on_text(111, "كويل لانوس")[0].text == "card for كويل لانوس"
    (out,) = c.on_text(111, "طلمبه باور")
    assert out.buttons == [[("طلمبه باور اوبترا", "item:6")], [("طلمبه باور لانوس", "item:7")]]


def test_buttons_under_messages(cfg):
    c, reports = chat(cfg)
    (item,) = c.on_button(111, "item:6")
    (page,) = c.on_button(111, "list:low:2")
    (opened,) = c.on_button(111, "open:idle")
    assert item.edit and page.edit and not opened.edit            # paging replaces, opening sends new
    assert reports.calls == [("item", 6), ("list", "low", 2), ("list", "idle", 0)]
    assert c.on_button(111, "list:low:x") == [] and c.on_button(111, "junk") == []


def test_previews_dont_move_memory_but_schedule_does(cfg):
    c, reports = chat(cfg)
    c.on_text(111, "/eod")
    c.on_text(111, "/daily@Elbaraga_car_bot")
    c.on_text(111, "/weekly")
    c.scheduled("eod")
    assert reports.calls == [("eod", False), ("daily", False), ("weekly",), ("eod", True)]


def test_no_data_yet(cfg):
    c, _ = chat(cfg, fail=True)
    assert c.on_text(111, "كويل لانوس")[0].text == messages.unavailable()
    assert c.scheduled("weekly").text == messages.unavailable()


def test_reports_asked_in_words(cfg):
    c, reports = chat(cfg)
    for text, call in [("تقرير اسبوع", ("weekly",)), ("التقرير الأسبوعي", ("weekly",)), ("النهارده", ("today",)),
                       ("تقرير آخر اليوم", ("eod", False)), ("تحديث العصر", ("daily", False)),
                       ("ايه النواقص", ("low",)), ("البضاعة الراكدة", ("idle",)), ("البطيء", ("list", "slow", 0))]:
        reports.calls.clear()
        c.on_text(111, text)
        assert reports.calls == [call], text
    reports.calls.clear()
    c.on_text(111, "العملاء")                   # this bot has no customer reports: looked up as a name
    assert reports.calls == [("ask", "العملاء")]


def test_names_are_not_mistaken_for_reports():
    from src.chat import report_asked
    assert report_asked("مين عليه فلوس") == "debt"
    assert report_asked("العملاء المتأخرين في الدفع") == "late"
    assert report_asked("العملاء اللي بطلوا يشتروا") == "stopped"
    assert report_asked("مين ممكن يعملي مشكلة") == "risk" and report_asked("التجار الخطر") == "risk"
    assert report_asked("التجار اللي نكمل معاهم") == "good" and report_asked("مين التجار الكويسين") == "good"
    assert report_asked("العملاء اللي لازم اخد بالي منهم") == "watch"
    for name in ["معرض الصفا عليه كام", "فاضل كام من طلمبه باور اوبترا", "حساب ورشة الأمانة", "اسبوع لانوس", "", "؟"]:
        assert report_asked(name) is None, name


def test_customer_reports_asked_in_words(shop_cfg):
    from datetime import datetime
    from src.reports import Reports
    from src.shop import Shop
    from src.state import State
    c = Chat(Reports(Shop(shop_cfg), shop_cfg, State(shop_cfg.state_path), as_of=datetime(2026, 9, 26, 18)), shop_cfg)
    assert c.on_text(111, "تقرير اسبوع")[0].text.startswith("📅 الأسبوع")
    assert c.on_text(111, "العملاء")[0].text.startswith("👥 العملاء")
    assert c.on_text(111, "مين عليه فلوس")[0].text.startswith("💳 المديونيات")
    assert c.on_text(111, "المتأخرين في الدفع")[0].text.startswith("⏰ متأخرين في الدفع")
    assert c.on_text(111, "مين ممكن يعملي مشكلة")[0].text.startswith("🔴 ممكن يعملولك مشكلة")
    assert c.on_text(111, "التجار الكويسين")[0].text.startswith("🟢 كمّل معاهم")
    assert c.on_text(111, "مركز النجمة عليه كام")[0].text.startswith("👤 مركز النجمة")


def test_demo_shop(tmp_path):
    from src import demo
    bot = demo.chat(tmp_path / "snapshot.db")
    assert bot.on_text(1, "كويل لانوس")[0].text.startswith("📦 كويل لانوس")
    assert bot.on_text(1, "تقرير الأسبوع")[0].text.startswith("📅 الأسبوع · 20/9 لـ 26/9")
