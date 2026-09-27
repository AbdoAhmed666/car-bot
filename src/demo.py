"""Try the bot on a made-up shop: no shop database, no Telegram needed.

    python -m src.demo                          build the made-up shop, show a few answers
    python -m src.demo "كويل لانوس" "العملاء"    ask it anything, as you would in Telegram

The shop is tests/fake_shop.py: real ELYASSER item names, invented numbers,
shaped like the real shop (mostly on credit, Fridays closed, customers who
stop buying or paying). Its "now" is its last day, 2026-09-26 18:00.

To chat with it in Telegram instead, put in .env:
    SNAPSHOT_PATH=data/demo/snapshot.db
    AS_OF=2026-09-26 18:00
and run python -m src.bot.
"""
import sys
from dataclasses import replace
from pathlib import Path

from . import config
from .chat import Chat
from .reports import Reports
from .shop import Shop
from .state import State

DEMO = Path(__file__).resolve().parent.parent / "data" / "demo" / "snapshot.db"
SAMPLES = ["تقرير الأسبوع", "فاضل كام من طلمبه باور اوبترا", "مؤسسة التوفيق عليه كام", "مين ممكن يعملي مشكلة"]


def build(path=DEMO) -> Path:
    """The made-up shop's snapshot, with its demand forecast (made once, ~10 s)."""
    from tests import fake_shop
    if not path.exists():
        print("building the made-up shop (once)...", file=sys.stderr)
        fake_shop.snapshot(path)
    return path


def chat(path=DEMO) -> Chat:
    from tests import fake_shop
    cfg = config.load()
    cfg = replace(cfg, snapshot_path=build(path), state_path=path.with_name("state.db"),
                  allowed_users=frozenset({1}), as_of=fake_shop.EXPORTED_AT)
    return Chat(Reports(Shop(cfg), cfg, State(cfg.state_path), cfg.as_of), cfg)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    bot = chat()
    for text in argv or SAMPLES:
        print(f"\n>>> {text}\n")
        for out in bot.on_text(1, text):
            print(out.text)
            for row in out.buttons:
                print("   " + "   ".join(f"[{label}]" for label, _ in row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
