"""The laptop bot's schedule (no network)."""
from dataclasses import replace

from src import bot
from tests.test_chat import FakeReports


def test_schedule(cfg):
    app = bot.build_app(replace(cfg, telegram_token="123:ABC", weekly_day=5), reports=FakeReports())
    jobs = {j.name: j for j in app.job_queue.jobs()}
    assert set(jobs) == {"daily", "end_of_day", "weekly"}
    assert "day_of_week='sat'" in str(jobs["weekly"].trigger)
    assert "hour='16'" in str(jobs["daily"].trigger) and "minute='30'" in str(jobs["daily"].trigger)


def test_buttons_become_telegram_markup():
    from src.chat import Out
    markup = bot.markup(Out("x", [[("a", "item:1"), ("b", "item:2")]]))
    assert [[b.callback_data for b in row] for row in markup.inline_keyboard] == [["item:1", "item:2"]]
    assert bot.markup(Out("x", keyboard=True)) is bot.KEYBOARD
    assert bot.markup(Out("x")) is None
