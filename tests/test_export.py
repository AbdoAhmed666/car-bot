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
    assert counts["items"] == 37 and counts["customers"] == 13 and counts["invoices"] > 1000
    assert counts["ledger"] > 100 and counts["accounts"] == 13     # customer accounts only, not the drawer
    assert "تيش ميزان خلفي بوما CTR" in names                      # padding spaces removed


def test_arrivals_are_purchases_only(shop_cfg):
    """When stock came in from a supplier: a customer's return or a sale is not an arrival."""
    from datetime import datetime
    got = Shop(shop_cfg).arrivals()
    assert len(got) == 37                                          # every item, the deleted one too
    assert got[36] == (datetime(2026, 9, 16, 11, 0), datetime(2026, 9, 16, 11, 0))    # the new item
    first, last = got[29]                                          # returned 5 days ago: not counted
    assert first == last and last < datetime(2026, 1, 1)
    # a date in the past only knows what had arrived by then
    assert 36 not in Shop(shop_cfg).arrivals(end=datetime(2026, 9, 1))


def test_old_snapshot_without_arrivals(own_db, shop_cfg):
    from dataclasses import replace
    db = sqlite3.connect(own_db)
    db.execute("DROP TABLE arrivals")
    db.commit()
    db.close()
    assert Shop(replace(shop_cfg, snapshot_path=own_db)).arrivals() == {}


def test_export_goes_on_without_arrivals():
    """If the program's stock ledger can't be read, the snapshot is written without it;
    any other table missing stops the export."""
    import pyodbc

    class Conn:
        def __init__(self, broken):
            self.broken = broken

        def cursor(self):
            conn = self

            class Cursor:
                description = [("x",)]

                def execute(self, sql):
                    if conn.broken in sql:
                        raise pyodbc.ProgrammingError(f"Invalid object name '{conn.broken}'")

                def fetchall(self):
                    return []
            return Cursor()

    assert export.read_source(Conn("dbo.Item_store"))["arrivals"] == []
    with pytest.raises(export.ExportError):
        export.read_source(Conn("dbo.Sal_Details"))


@pytest.fixture
def own_db(fake_snapshot, tmp_path):
    import shutil
    path = tmp_path / "own.db"
    shutil.copy(fake_snapshot, path)
    return path


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
