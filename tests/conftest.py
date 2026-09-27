import os
from dataclasses import replace
from datetime import time
from pathlib import Path

import pytest

from src import config
from tests import fake_shop

REPLICA = Path(__file__).with_name("elyasser_replica.sql")


@pytest.fixture
def cfg(tmp_path):
    return config.Config(
        telegram_token="", allowed_users=frozenset({111}), db_server="", db_name="", db_user="",
        db_password="", timezone="Africa/Cairo", daily_update=time(16, 30), end_of_day=time(23, 30),
        weekly_day=3, weekly_time=time(23, 45), velocity_days=60, low_stock_days=7, idle_days=90,
        min_sold=3, state_path=tmp_path / "state.db", snapshot_path=tmp_path / "snapshot.db")


@pytest.fixture(scope="session")
def fake_snapshot(tmp_path_factory):
    """The fake shop as the SQLite snapshot the bot reads, with the forecast marked
    as not in use (the fake shop sells at constant rates: whether the model beats
    the average there is a coin toss). tests/test_forecast.py turns it on."""
    import sqlite3
    path = fake_shop.snapshot(tmp_path_factory.mktemp("shop") / "snapshot.db")
    db = sqlite3.connect(path)
    db.execute("UPDATE meta SET value = '0' WHERE key = 'forecast_used'")
    db.commit()
    db.close()
    return path


@pytest.fixture
def shop_cfg(cfg, fake_snapshot):
    return replace(cfg, snapshot_path=fake_snapshot)


@pytest.fixture(scope="session")
def sql_server():
    """A SQL Server database with the ELYASSER replica tables and the fake shop,
    at compatibility level 100 like the shop's SQL Server 2008.

    Needs CARBOT_TEST_SERVER, plus CARBOT_TEST_USER / CARBOT_TEST_PASSWORD for a SQL login.
    """
    server = os.environ.get("CARBOT_TEST_SERVER")
    if not server:
        pytest.skip("set CARBOT_TEST_SERVER to run the SQL Server tests")
    import pyodbc
    from src.export import conn_str, pick_driver

    user, password = os.environ.get("CARBOT_TEST_USER", ""), os.environ.get("CARBOT_TEST_PASSWORD", "")
    driver, name = pick_driver(), "carbot_test"
    master = pyodbc.connect(conn_str(driver, server, "master", user, password), autocommit=True)
    master.execute(f"IF DB_ID('{name}') IS NOT NULL BEGIN "
                   f"ALTER DATABASE {name} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE {name}; END")
    master.execute(f"CREATE DATABASE {name}")
    master.execute(f"ALTER DATABASE {name} SET COMPATIBILITY_LEVEL = 100")
    master.close()
    conn = pyodbc.connect(conn_str(driver, server, name, user, password))
    conn.execute(REPLICA.read_text(encoding="utf-8"))
    conn.commit()
    fake_shop.load(conn)
    conn.close()
    return {"db_server": server, "db_name": name, "db_user": user, "db_password": password}
