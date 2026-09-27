from datetime import datetime, time

from src import config


def test_settings_from_env(monkeypatch, tmp_path):
    for key, value in {"ALLOWED_USERS": "111, 222", "WEEKLY_DAY": "Saturday", "DAILY_UPDATE": "16:45",
                       "AS_OF": "2026-09-26 18:00", "DB_SERVER": "shop", "DB_NAME": "auto",
                       "SERVER_URL": "https://x.pythonanywhere.com ", "UPLOAD_TOKEN": "u", "WEBHOOK_SECRET": "w",
                       "SNAPSHOT_PATH": ""}.items():
        monkeypatch.setenv(key, value)
    cfg = config.load(tmp_path / "missing.env")
    assert cfg.allowed_users == {111, 222}
    assert cfg.weekly_day == 5 and cfg.daily_update == time(16, 45)
    assert cfg.as_of == datetime(2026, 9, 26, 18, 0)
    assert (cfg.db_server, cfg.db_name) == ("shop", "auto")
    assert (cfg.server_url, cfg.upload_token, cfg.webhook_secret) == ("https://x.pythonanywhere.com", "u", "w")
    assert cfg.snapshot_path == config.ROOT / "data" / "snapshot.db"          # empty = the default


def test_defaults(monkeypatch, tmp_path):
    for key in ["ALLOWED_USERS", "WEEKLY_DAY", "DAILY_UPDATE", "AS_OF", "DB_SERVER", "DB_NAME"]:
        monkeypatch.delenv(key, raising=False)
    cfg = config.load(tmp_path / "missing.env")
    assert cfg.allowed_users == frozenset() and cfg.as_of is None
    assert (cfg.db_server, cfg.db_name, cfg.weekly_day) == (r".\SQLEXPRESS", "ELyasserDB", 3)
