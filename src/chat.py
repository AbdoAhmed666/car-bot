"""What the bot answers, whatever carries the messages: long polling on the
laptop (src/bot.py) or a webhook on the server (src/webapp.py).

Takes who wrote and what they wrote (or which button they pressed), returns
the messages to send back.
"""
from dataclasses import dataclass, field

from . import messages
from .normalize import tokens
from .shop import ShopUnavailable

# Reports asked for in words ("تقرير الأسبوع", "مين عليه فلوس") instead of with the buttons.
# A message is one only if all its words (after the fillers) are from that report's list and
# at least one is a core word, so "فلان عليه كام" still looks up the customer. Words are as
# normalize.tokens() gives them: spelling folded, "ال" dropped. First match wins.
_CUSTOMERS = {"عملاء", "عملا", "عميل", "زباين", "زبون", "تجار", "تاجر"}
_SALES = {"مبيعات", "بيع", "مكسب", "ارباح", "ربح"}
REPORT_WORDS = [
    # report,     core words (one needed),                        other words allowed
    ("eod",       {"اخر", "تقفيل"},                                {"يوم", "نهارده", "انهارده", "ليله"} | _SALES),
    ("risk",      {"خطر", "مشكله", "مشاكل", "خطرين"},               _CUSTOMERS | {"مين", "يعملي", "يعملولي", "يعملوا",
                                                                                 "يعمل", "ممكن", "تجار", "تاجر"}),
    ("watch",     {"بالك", "بالي", "حذر"},                          _CUSTOMERS | {"خلي", "مين", "اخد", "لازم", "منهم"}),
    ("good",      {"كويسين", "كويس", "نكمل", "كمل", "احسن", "افضل"}, _CUSTOMERS | {"مين", "معاهم", "معاه", "تجار",
                                                                                 "تاجر"}),
    ("late",      {"متاخرين", "متاخر", "تحصيل", "مدفعوش", "مدفعش"}, _CUSTOMERS | {"دفع", "فلوس"}),
    ("debt",      {"مديونيات", "مديونيه", "ديون", "اجل", "فلوس"},  _CUSTOMERS | {"عليهم", "عليه", "مين", "برا", "بره"}),
    ("stopped",   {"بطلوا", "بطلو", "وقفوا", "مبقوش"},             _CUSTOMERS | {"يشتروا", "يشترو", "شرا"}),
    ("customers", _CUSTOMERS,                                      set()),
    ("week",      {"اسبوع", "اسبوعي", "اسبوعيه"},                  _SALES),
    ("daily",     {"عصر", "تحديث"},                                {"نهارده", "انهارده"}),
    ("low",       {"نواقص", "ناقص", "نقص", "هيخلص", "خلصان"},       {"قرب", "يخلص", "اصناف", "صنف", "بضاعه"}),
    ("idle",      {"راكد", "رواكد", "راكده", "ركود"},               {"اصناف", "بضاعه"}),
    ("slow",      {"بطيء", "بطيي", "بطي"},                         {"اصناف", "بضاعه"}),
    ("today",     {"نهارده", "انهارده", "يوم"},                     _SALES),
]
FILLERS = {"تقرير", "تقارير", "عايز", "عاوز", "عايزه", "ابعت", "ابعتلي", "هات", "هاتلي", "وريني", "اعرض",
           "ايه", "اخبار", "بتاع", "بتاعه", "لو", "سمحت", "فضلك", "من", "يا", "بوت", "كده", "كدا", "ممكن",
           "شوف", "قولي", "قوللي", "اديني", "عن", "في", "لي", "اللي", "الي", "بتوع", "كل"}


def report_asked(text):
    """Which report the words ask for, or None."""
    words = {w for w in tokens(text) if w not in FILLERS}
    if not words:
        return None
    for name, core, other in REPORT_WORDS:
        if words & core and words <= core | other:
            return name
    return None


@dataclass
class Out:
    text: str
    buttons: list = field(default_factory=list)    # inline buttons: rows of (label, callback data)
    keyboard: bool = False                          # also show the main keyboard (messages.BUTTONS)
    edit: bool = False                              # replace the message the pressed button was on


class Chat:
    def __init__(self, reports, cfg):
        self.reports, self.cfg = reports, cfg

    def allowed(self, user_id) -> bool:
        return user_id in self.cfg.allowed_users

    def _out(self, make, edit=False) -> Out:
        try:
            reply = make()
        except ShopUnavailable:
            return Out(messages.unavailable())
        return Out(reply.text, reply.buttons, edit=edit)

    def on_text(self, user_id, text) -> list:
        if not self.allowed(user_id):
            return [Out(messages.refused(user_id))]
        r = self.reports
        text = (text or "").strip()
        if text.startswith("/"):
            command = text.split()[0][1:].split("@")[0].lower()
            previews = {"daily": lambda: r.daily_update(save=False),     # the memory doesn't move,
                        "eod": lambda: r.end_of_day(save=False),         # so the real report still
                        "weekly": r.weekly}                              # covers the whole day
            if command in previews:
                return [self._out(previews[command])]
            return [Out(messages.welcome(self.cfg), keyboard=True)]
        buttons = {messages.BUTTON_TODAY: r.today, messages.BUTTON_WEEK: r.weekly,
                   messages.BUTTON_LOW: r.low, messages.BUTTON_IDLE: r.idle}
        if hasattr(r, "customers"):
            buttons[messages.BUTTON_CUSTOMERS] = r.customers
        if text in buttons:
            return [self._out(buttons[text])]
        asked = self._report(report_asked(text))
        if asked:
            return [self._out(asked)]
        return [self._out(lambda: r.ask(text))]

    def _report(self, name):
        """The call that makes a report asked for in words; None if this bot can't make it."""
        r = self.reports
        calls = {"today": lambda: r.today(), "week": lambda: r.weekly(), "low": lambda: r.low(),
                 "idle": lambda: r.idle(), "slow": lambda: r.list_page("slow"),
                 "daily": lambda: r.daily_update(save=False), "eod": lambda: r.end_of_day(save=False)}
        if hasattr(r, "customers"):
            calls["customers"] = lambda: r.customers()
            for kind in ("debt", "late", "stopped", "risk", "watch", "good"):
                calls[kind] = lambda kind=kind: r.list_page(kind)
        return calls.get(name)

    def on_button(self, user_id, data) -> list:
        if not self.allowed(user_id):
            return []
        kind, _, rest = (data or "").partition(":")
        r = self.reports
        if kind == "item" and rest.isdigit():
            return [self._out(lambda: r.item(int(rest)), edit=True)]
        if kind == "customer" and rest.isdigit() and hasattr(r, "customer"):
            return [self._out(lambda: r.customer(int(rest)), edit=True)]
        if kind == "open":
            return [self._out(lambda: r.list_page(rest))]
        if kind == "list":
            list_kind, _, number = rest.partition(":")
            if number.isdigit():
                return [self._out(lambda: r.list_page(list_kind, int(number)), edit=True)]
        if kind == "sales" and hasattr(r, "sales_page"):
            # "sales:after:upto" under a report opens the details as a new message;
            # "sales:after:upto:page" turns its pages
            parts = rest.split(":")
            if len(parts) in (2, 3) and all(x.isdigit() for x in parts):
                after, upto, number = int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) == 3 else 0
                return [self._out(lambda: r.sales_page(after, upto, number), edit=len(parts) == 3)]
        return []

    def scheduled(self, which) -> Out:
        """A scheduled report ("daily", "eod", "weekly"), moving the bot's memory."""
        make = {"daily": self.reports.daily_update, "eod": self.reports.end_of_day,
                "weekly": self.reports.weekly}[which]
        return self._out(make)
