"""Settings, read from .env in the repo root. See .env.example for every key."""
import os
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Python's weekday numbers (Monday = 0)
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass(frozen=True)
class Config:
    telegram_token: str
    allowed_users: frozenset       # Telegram user ids that may use the bot
    db_server: str                 # for export: ".\SQLEXPRESS" on the laptop, "shop" on the shop PC
    db_name: str                   # "ELyasserDB" on the laptop, "auto" on the shop PC
    db_user: str                   # empty = Windows login
    db_password: str
    timezone: str
    daily_update: time
    end_of_day: time
    weekly_day: int                # Python weekday, Monday = 0
    weekly_time: time
    velocity_days: int             # sales window for "sells N a day"
    low_stock_days: int            # warn when stock lasts fewer days than this
    idle_days: int                 # no sale for this long = idle stock
    min_sold: int                  # sold at least this many in the window to count as "selling"
    state_path: Path
    snapshot_path: Path = None     # the SQLite copy of the shop data the bot reads (src/export.py)
    server_url: str = ""           # shop PC: where src/sync.py sends the snapshot
    upload_token: str = ""         # shared secret between src/sync.py and the server's /upload
    webhook_secret: str = ""       # Telegram sends it with every update, so the server knows it's Telegram
    as_of: datetime = None         # testing on an old copy: act as if it were this moment


def _time(value: str) -> time:
    hours, minutes = value.strip().split(":")
    return time(int(hours), int(minutes))


def _ids(value: str) -> frozenset:
    return frozenset(int(x) for x in value.replace(" ", "").split(",") if x)


def load(env_file=None) -> Config:
    load_dotenv(env_file or ROOT / ".env")
    env = os.environ.get
    return Config(
        telegram_token=env("TELEGRAM_TOKEN", "").strip(),
        allowed_users=_ids(env("ALLOWED_USERS", "")),
        db_server=env("DB_SERVER", r".\SQLEXPRESS").strip(),
        db_name=env("DB_NAME", "ELyasserDB").strip(),
        db_user=env("DB_USER", "").strip(),
        db_password=env("DB_PASSWORD", ""),
        timezone=env("TIMEZONE", "Africa/Cairo").strip(),
        daily_update=_time(env("DAILY_UPDATE", "16:30")),
        end_of_day=_time(env("END_OF_DAY", "23:30")),
        weekly_day=WEEKDAYS[env("WEEKLY_DAY", "thu").strip().lower()[:3]],
        weekly_time=_time(env("WEEKLY_TIME", "23:45")),
        velocity_days=int(env("VELOCITY_DAYS", "60")),
        low_stock_days=int(env("LOW_STOCK_DAYS", "7")),
        idle_days=int(env("IDLE_DAYS", "90")),
        min_sold=int(env("MIN_SOLD", "3")),
        state_path=Path(env("STATE_PATH", str(ROOT / "data" / "state.db"))),
        snapshot_path=Path(env("SNAPSHOT_PATH", "").strip() or str(ROOT / "data" / "snapshot.db")),
        server_url=env("SERVER_URL", "").strip(),
        upload_token=env("UPLOAD_TOKEN", "").strip(),
        webhook_secret=env("WEBHOOK_SECRET", "").strip(),
        as_of=datetime.strptime(env("AS_OF"), "%Y-%m-%d %H:%M") if env("AS_OF", "").strip() else None,
    )
