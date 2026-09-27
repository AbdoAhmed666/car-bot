"""Scheduled reports from the server, to every allowed user.

PythonAnywhere's free plan has no scheduled tasks for accounts made after
January 2026, so nothing here runs on a clock. Instead, whenever something
reaches the server (a snapshot from the shop PC, a message to the bot, or a
free pinger such as cron-job.org opening /tick every 15 minutes), it sends
whatever report is due and was not sent yet:

    daily    after DAILY_UPDATE, once the shop PC has sent something that day
    eod      after END_OF_DAY (until 6 am), if the shop PC sent something since 6 am
             (nothing on a day the shop was closed)
    weekly   at the same time as eod, on WEEKLY_DAY

    python -m src.push                          send whatever is due now (same as /tick)
    python -m src.push daily | eod | weekly     send that one now, due or not
"""
import logging
import sys
from datetime import datetime, time, timedelta

from . import config
from .chat import Chat
from .reports import Reports
from .shop import Shop, ShopUnavailable
from .state import State
from .telegram_api import Telegram

log = logging.getLogger("car-bot")
SENT = {"daily": "daily_sent", "eod": "eod_sent", "weekly": "weekly_sent"}     # state key: day it went out for


def due(cfg, reports, state) -> list:
    """[(report, day)] due now and not sent yet for that day, in sending order."""
    now = reports.now()
    exported = reports.shop.exported_at()
    if exported is None:
        return []
    out = []
    today = now.date().isoformat()
    if now.time() >= cfg.daily_update and exported.date() == now.date() and state.get(SENT["daily"]) != today:
        out.append(("daily", today))

    day = reports.business_day().date()           # until 6 am it is still the day before
    opened = datetime.combine(day, time(6))
    closing = datetime.combine(day, cfg.end_of_day) + timedelta(days=1 if cfg.end_of_day < time(6) else 0)
    if now >= closing:
        if exported >= opened and state.get(SENT["eod"]) != day.isoformat():
            out.append(("eod", day.isoformat()))
        if day.weekday() == cfg.weekly_day and state.get(SENT["weekly"]) != day.isoformat():
            out.append(("weekly", day.isoformat()))
    return out


def run_due(cfg, reports, state, tg) -> list:
    """Send the reports that are due; returns their names."""
    try:
        jobs = due(cfg, reports, state)
    except ShopUnavailable:
        return []
    chat = Chat(reports, cfg)
    for job, day in jobs:
        tg.broadcast(cfg.allowed_users, chat.scheduled(job))
        state.set(SENT[job], day)
        log.info("sent %s for %s to %d users", job, day, len(cfg.allowed_users))
    return [job for job, _ in jobs]


def main(argv=None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    argv = sys.argv[1:] if argv is None else argv
    which = argv[0] if argv else "due"
    if which not in ("due", "daily", "eod", "weekly"):
        print(__doc__)
        return 2
    cfg = config.load()
    state = State(cfg.state_path)
    reports = Reports(Shop(cfg), cfg, state, cfg.as_of)
    tg = Telegram(cfg.telegram_token)
    if which == "due":
        print("sent:", ", ".join(run_due(cfg, reports, state, tg)) or "nothing due")
    else:
        tg.broadcast(cfg.allowed_users, Chat(reports, cfg).scheduled(which))
        print(f"sent {which} to {len(cfg.allowed_users)} users")
    return 0


if __name__ == "__main__":
    sys.exit(main())
