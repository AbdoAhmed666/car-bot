"""The snapshot: what src/export.py copies from the shop's database."""
import sqlite3

import pytest

from src import export
from src.shop import Shop
from tests import fake_shop


def test_snapshot_tables(fake_snapshot):
    db = sqlite3.connect(fake_snapshot)
    counts = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in export.TABLES}
    names = [r[0] for r in db.execute("SELECT name FROM items")]
    db.close()
    assert counts["items"] == 36 and counts["customers"] == 13 and counts["invoices"] > 1000
    assert counts["ledger"] > 100 and counts["accounts"] == 13     # customer accounts only, not the drawer
    assert "تيش ميزان خلفي بوما CTR" in names                      # padding spaces removed


def test_payments_are_marked(fake_snapshot):
    db = sqlite3.connect(fake_snapshot)
    marked = db.execute("SELECT COUNT(*), MIN(credit), MAX(debt) FROM ledger WHERE payment = 1").fetchone()
    sales = db.execute("SELECT COUNT(*) FROM ledger WHERE payment = 0 AND debt > 0").fetchone()[0]
    db.close()
    assert marked[0] > 50 and marked[1] > 0 and marked[2] == 0     # payments: money in, never a sale
    assert sales > 100
    assert export._is_set(4088) and export._is_set("12") and not export._is_set(None)
    assert not export._is_set(0) and not export._is_set("  ")


def test_no_phone_numbers_copied(fake_snapshot):
    db = sqlite3.connect(fake_snapshot)
    columns = [r[1] for r in db.execute("PRAGMA table_info(customers)")]
    db.close()
    assert not {"mobile", "phone", "address"} & {c.lower() for c in columns}


def test_rewriting_keeps_readers_safe(tmp_path, cfg):
    path = tmp_path / "snap.db"
    fake_shop.snapshot(path)
    first = Shop(type(cfg)(**{**cfg.__dict__, "snapshot_path": path})).check()
    fake_shop.snapshot(path)                     # written again over the old one
    assert not path.with_name("snap.db.tmp").exists()
    assert Shop(type(cfg)(**{**cfg.__dict__, "snapshot_path": path})).check()["invoices"] == first["invoices"]


def test_export_from_sql_server(sql_server, cfg, tmp_path):
    """The real queries on the ELYASSER replica give exactly the snapshot the tests use."""
    from dataclasses import replace
    conn = export.connect(replace(cfg, **sql_server))
    try:
        got = export.read_source(conn)
    finally:
        conn.close()
    expected = export.transform(fake_shop.source_rows())
    for table in export.TABLES:
        assert sorted(got[table]) == sorted(expected[table]), table

    counts = export.export(replace(cfg, **sql_server), tmp_path / "out.db")
    assert counts["invoices"] == len(expected["invoices"])
