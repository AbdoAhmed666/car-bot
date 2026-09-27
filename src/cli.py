"""The bot's answers in the terminal, without Telegram.

    python -m src.export          (refresh the snapshot first)
    python -m src.cli check
    python -m src.cli ask "فاضل كام من طلمبه باور اوبترا"
    python -m src.cli today | low | idle | slow | daily | eod | weekly
    python -m src.cli weekly --as-of "2026-09-24 23:45" --out weekly.txt

Nothing is saved: the daily and end-of-day reports don't move the bot's
memory. --as-of computes a report as if it were that moment (by invoice
dates), to try the reports on an old copy of the database. --out also writes
the text to a UTF-8 file, which Notepad shows properly if the terminal can't
draw Arabic.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import config
from .reports import Reports
from .shop import Shop, ShopUnavailable
from .state import State

COMMANDS = ["check", "ask", "today", "low", "idle", "slow", "daily", "eod", "weekly"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("text", nargs="?", default="", help="the question, for ask")
    parser.add_argument("--as-of", help='pretend it is this moment: "YYYY-MM-DD HH:MM"')
    parser.add_argument("--out", help="also write the text to this file")
    parser.add_argument("--env", help=".env file to read (default: the one in the repo)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    cfg = config.load(args.env)
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d %H:%M") if args.as_of else cfg.as_of
    shop = Shop(cfg)
    reports = Reports(shop, cfg, State(cfg.state_path), as_of)
    run = {"today": reports.today, "low": reports.low, "idle": reports.idle, "weekly": reports.weekly,
           "slow": lambda: reports.list_page("slow"), "ask": lambda: reports.ask(args.text),
           "daily": lambda: reports.daily_update(save=False), "eod": lambda: reports.end_of_day(save=False)}
    try:
        if args.command == "check":
            r = shop.check()
            text = (f"snapshot: {cfg.snapshot_path} (exported {r['exported_at']})\n"
                    f"items: {r['items']:,}  customers: {r['customers']:,}  invoices: {r['invoices']:,}"
                    f"  last invoice: {r['last_invoice']}")
        else:
            reply = run[args.command]()
            buttons = [f"[{label}  ->  {data}]" for row in reply.buttons for label, data in row]
            text = "\n".join([reply.text, *buttons])
    except ShopUnavailable as e:
        print(f"Can't read the shop database: {e}", file=sys.stderr)
        return 1

    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
