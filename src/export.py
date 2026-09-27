"""Copy what the bot needs from the ELYASSER database into a small SQLite file.

    python -m src.export              (writes data/snapshot.db)

Runs where the shop's database is: the shop PC (DB_SERVER=shop) or the
laptop with the restored copy. The bot itself only ever reads the snapshot,
so it can run anywhere, even when the shop PC is off.

Every query on the shop's database is a SELECT that reads WITH (NOLOCK), so
the program never waits on it, in SQL Server 2008 syntax (the shop PC runs
2008). tests/test_sql_rules.py checks both. No phone numbers or addresses
are copied.
"""
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config

# best first; the shop PC (SQL Server 2008) usually only has the last two
DRIVERS = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server",
           "SQL Server Native Client 11.0", "SQL Server Native Client 10.0", "SQL Server")

SNAPSHOT_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, code TEXT, stock REAL, price REAL, cost REAL,
                    category INTEGER, deleted INTEGER);
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, is_customer INTEGER, account_id INTEGER,
                        credit_limit REAL, max_days INTEGER, deleted INTEGER);
CREATE TABLE invoices (id INTEGER, date TEXT, customer_id INTEGER, total REAL, profit REAL, discount REAL,
                       credit INTEGER, paid REAL);
CREATE TABLE invoice_lines (id INTEGER, invoice_id INTEGER, item_id INTEGER, qty REAL, price REAL,
                            total REAL, profit REAL);
CREATE TABLE returns (id INTEGER, date TEXT, customer_id INTEGER, total REAL, profit REAL);
CREATE TABLE return_lines (id INTEGER, return_id INTEGER, item_id INTEGER, qty REAL, total REAL, profit REAL);
CREATE TABLE deleted_lines (id INTEGER, invoice_id INTEGER, item_name TEXT, qty REAL, price REAL, date TEXT,
                            customer_name TEXT);
CREATE TABLE accounts (id INTEGER, name TEXT, opening REAL);
CREATE TABLE ledger (id INTEGER, account_id INTEGER, date TEXT, debt REAL, credit REAL, balance REAL,
                     payment INTEGER);
CREATE TABLE forecasts (item_id INTEGER PRIMARY KEY, next_30 REAL);
CREATE INDEX ix_invoices_id ON invoices (id);
CREATE INDEX ix_invoices_date ON invoices (date);
CREATE INDEX ix_invoices_customer ON invoices (customer_id);
CREATE INDEX ix_lines_invoice ON invoice_lines (invoice_id);
CREATE INDEX ix_lines_item ON invoice_lines (item_id);
CREATE INDEX ix_returns_date ON returns (date);
CREATE INDEX ix_return_lines_return ON return_lines (return_id);
CREATE INDEX ix_ledger_account ON ledger (account_id);
"""


def _text(value) -> str:
    """Item and customer names come padded with runs of spaces; keep single ones."""
    return " ".join(str(value).split()) if value is not None else ""


def _num(value) -> float:
    return round(float(value), 4) if value is not None else 0.0


def _int(value) -> int:
    return int(value) if value is not None else 0


def _is_set(value) -> bool:
    return value is not None and str(value).strip() not in ("", "0")


def _date(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value is not None else None


# snapshot table: (source query, row -> snapshot tuple)
TABLES = {
    "items": ("""
        SELECT i.id_item, i.ARname, i.InternationalCode, i.net_balance, i.BigPr0, i.cost, i.IdTypeItem1, i.Deleted
        FROM dbo.Item i WITH (NOLOCK)""",
        lambda r: (_int(r["id_item"]), _text(r["ARname"]), _text(r["InternationalCode"]), _num(r["net_balance"]),
                   _num(r["BigPr0"]), _num(r["cost"]), _int(r["IdTypeItem1"]), 1 if r["Deleted"] else 0)),
    "customers": ("""
        SELECT c.id_cust, c.Aname, c.IsCustomer, c.id_account, c.credit_limit, c.MaxDayOfCredit, c.Deleted
        FROM dbo.cust c WITH (NOLOCK)""",
        lambda r: (_int(r["id_cust"]), _text(r["Aname"]), _int(r["IsCustomer"]), _int(r["id_account"]),
                   _num(r["credit_limit"]), _int(r["MaxDayOfCredit"]), 1 if r["Deleted"] else 0)),
    "invoices": ("""
        SELECT s.id_sal, s.pdate, s.id_cust, s.Total, s.Profit, s.cashDiscount, s.TypePaied, s.AmountPaid
        FROM dbo.Sal_Invoice s WITH (NOLOCK)""",
        lambda r: (_int(r["id_sal"]), _date(r["pdate"]), _int(r["id_cust"]), _num(r["Total"]), _num(r["Profit"]),
                   _num(r["cashDiscount"]), 1 if r["TypePaied"] == 1 else 0, _num(r["AmountPaid"]))),
    "invoice_lines": ("""
        SELECT d.id, d.id_sal, d.id_item, d.qu, d.pr, d.total_item, d.profit
        FROM dbo.Sal_Details d WITH (NOLOCK)""",
        lambda r: (_int(r["id"]), _int(r["id_sal"]), _int(r["id_item"]), _num(r["qu"]), _num(r["pr"]),
                   _num(r["total_item"]), _num(r["profit"]))),
    "returns": ("""
        SELECT r.id_Rsal, r.pdate, r.id_cust, r.Total, r.Profit
        FROM dbo.Rsal_invoice r WITH (NOLOCK)""",
        lambda r: (_int(r["id_Rsal"]), _date(r["pdate"]), _int(r["id_cust"]), _num(r["Total"]), _num(r["Profit"]))),
    "return_lines": ("""
        SELECT d.id, d.id_RSal, d.id_item, d.qu, d.total_item, d.Profit
        FROM dbo.Rsal_details d WITH (NOLOCK)""",
        lambda r: (_int(r["id"]), _int(r["id_RSal"]), _int(r["id_item"]), _num(r["qu"]), _num(r["total_item"]),
                   _num(r["Profit"]))),
    "deleted_lines": ("""
        SELECT x.id, x.id_sal, x.ARname, x.qu, x.pr, x.pdate, x.Cust_Name
        FROM dbo.Sal_Deleted x WITH (NOLOCK)""",
        lambda r: (_int(r["id"]), _int(r["id_sal"]), _text(r["ARname"]), _num(r["qu"]), _num(r["pr"]),
                   _date(r["pdate"]), _text(r["Cust_Name"]))),
    # accounting, only for customer accounts (for balances)
    "accounts": ("""
        SELECT t.id, t.aname, t.Begin_balance
        FROM dbo.Tree t WITH (NOLOCK)
        WHERE t.id IN (SELECT c.id_account FROM dbo.cust c WITH (NOLOCK))""",
        lambda r: (_int(r["id"]), _text(r["aname"]), _num(r["Begin_balance"]))),
    # what a customer owes is the sum of debt - credit over all their entries: it matches
    # the program's own CustBalance (tools/check_balances.py). The running `balance`
    # column does not, because entries are not always stored in date order.
    # An entry with a cash receipt (id_CashCome) is a payment.
    "ledger": ("""
        SELECT a.id, a.id_Account, a.pdate, a.debt, a.credit, a.balance, a.id_CashCome
        FROM dbo.Tree_Account a WITH (NOLOCK)
        WHERE a.id_Account IN (SELECT c.id_account FROM dbo.cust c WITH (NOLOCK))""",
        lambda r: (_int(r["id"]), _int(r["id_Account"]), _date(r["pdate"]), _num(r["debt"]), _num(r["credit"]),
                   _num(r["balance"]), 1 if _is_set(r["id_CashCome"]) else 0)),
}


class ExportError(Exception):
    """The shop's database can't be read (program closed, wrong settings, ...)."""


# --- connecting to the shop's SQL Server ---------------------------------

def _odbc():
    """pyodbc, loaded only to talk to SQL Server: the demo and the rest run without it."""
    import pyodbc
    return pyodbc


def pick_driver() -> str:
    installed = set(_odbc().drivers())
    for driver in DRIVERS:
        if driver in installed:
            return driver
    raise ExportError("No SQL Server ODBC driver is installed")


def conn_str(driver, server, database, user="", password=""):
    parts = [f"DRIVER={{{driver}}}", f"SERVER={server}",
             "DATABASE={" + database.replace("}", "}}") + "}", "APP=car-bot"]
    if user:
        parts += [f"UID={user}", "PWD={" + password.replace("}", "}}") + "}"]
    else:
        parts.append("Trusted_Connection=yes")
    if driver.startswith("ODBC Driver 18"):
        parts.append("Encrypt=no")      # local connection; 18 would demand a trusted certificate
    return ";".join(parts)


def _program_instance(driver) -> str:
    """Pipe of the private SQL instance ELYASSER starts for itself (User Instance=True).

    The main SQLEXPRESS instance lists it while it is alive: while the program
    is open, and for a while after it closes.
    """
    conn = _odbc().connect(conn_str(driver, r".\SQLEXPRESS", "master"), timeout=10, autocommit=True)
    try:
        rows = conn.cursor().execute(
            "SELECT owning_principal_name, instance_pipe_name FROM sys.dm_os_child_instances "
            "WHERE heart_beat = 'alive'").fetchall()
    finally:
        conn.close()
    if not rows:
        raise ExportError("ELYASSER is not open")
    me = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lower()
    mine = [r for r in rows if (r[0] or "").lower() == me] or rows
    return "np:" + mine[0][1]


def _biggest_database(driver, server, user, password) -> str:
    conn = _odbc().connect(conn_str(driver, server, "master", user, password), timeout=10, autocommit=True)
    try:
        row = conn.cursor().execute(
            "SELECT TOP 1 d.name FROM sys.databases d "
            "JOIN sys.master_files mf ON mf.database_id = d.database_id "
            "WHERE d.database_id > 4 GROUP BY d.name ORDER BY SUM(mf.size) DESC").fetchone()
    finally:
        conn.close()
    if not row:
        raise ExportError(f"No database on {server}")
    return row[0]


def connect(cfg):
    """Open the shop's database, as set in .env (DB_SERVER / DB_NAME)."""
    pyodbc = _odbc()
    try:
        driver = pick_driver()
        server, database, user = cfg.db_server, cfg.db_name, cfg.db_user
        if server.lower() == "shop":
            server, user = _program_instance(driver), ""        # user instances: Windows login only
        if database.lower() == "auto":
            database = _biggest_database(driver, server, user, cfg.db_password)
        conn = pyodbc.connect(conn_str(driver, server, database, user, cfg.db_password),
                              timeout=10, autocommit=True)
        conn.timeout = 120
        return conn
    except pyodbc.Error as e:
        raise ExportError(str(e)) from e


# --- reading and writing ---------------------------------------------------

def read_source(conn) -> dict:
    """{snapshot table: [row tuples]} read from the shop's database."""
    pyodbc = _odbc()
    out = {}
    cur = conn.cursor()
    for name, (sql, row) in TABLES.items():
        if not sql.lstrip().upper().startswith("SELECT"):
            raise ValueError("export only reads")
        try:
            cur.execute(sql)
        except pyodbc.Error as e:
            raise ExportError(f"{name}: {e}") from e
        cols = [c[0] for c in cur.description]
        out[name] = [row(dict(zip(cols, r))) for r in cur.fetchall()]
    return out


def transform(source_rows) -> dict:
    """Same as read_source, from rows already fetched ({table: [dict]}); used by the tests."""
    return {name: [row(r) for r in source_rows.get(name, [])] for name, (_, row) in TABLES.items()}


def write_snapshot(tables, path, exported_at=None, meta=None) -> Path:
    """Write the snapshot next to `path` and swap it in, so a reader never sees half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SNAPSHOT_SCHEMA)
        for name, rows in tables.items():
            if rows:
                marks = ", ".join("?" * len(rows[0]))
                db.executemany(f"INSERT INTO {name} VALUES ({marks})", rows)
        stamp = (exported_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        db.executemany("INSERT INTO meta VALUES (?, ?)",
                       [("exported_at", stamp), ("version", "1"), *(meta or {}).items()])
        db.commit()
    finally:
        db.close()
    for attempt in range(10):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:     # Windows: a reader has the old file open for a moment
            if attempt == 9:
                raise
            time.sleep(0.5)
    return path


def todays_forecast(path, as_of):
    """(rows, meta) of the forecast already in the snapshot at `path` if it was made
    on the same day, else None: the backtest takes a while, once a day is enough."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            meta = dict(db.execute("SELECT key, value FROM meta WHERE key LIKE 'forecast%'").fetchall())
            rows = db.execute("SELECT item_id, next_30 FROM forecasts").fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return None
    if "forecast_method" not in meta or not rows or meta.get("forecast_at", "")[:10] != f"{as_of:%Y-%m-%d}":
        return None
    return rows, meta


def with_forecasts(tables, as_of, reuse_from=None):
    """Add the demand forecast (src/forecast.py) to the tables; skipped if numpy /
    scikit-learn aren't installed, so the export itself never fails because of it."""
    found = todays_forecast(reuse_from, as_of) if reuse_from else None
    if found:
        rows, meta = found
        return {**tables, "forecasts": rows}, meta
    try:
        from . import forecast
        rows, meta = forecast.forecast_rows(tables, as_of)
    except ImportError as e:
        print(f"no forecast ({e}): pip install -r requirements-shop.txt", file=sys.stderr)
        rows, meta = [], {}
    return {**tables, "forecasts": rows}, meta


def export(cfg, path=None) -> dict:
    conn = connect(cfg)
    try:
        tables = read_source(conn)
    finally:
        conn.close()
    now, path = datetime.now(), path or cfg.snapshot_path
    tables, meta = with_forecasts(tables, now, reuse_from=path)
    write_snapshot(tables, path, now, meta)
    return {name: len(rows) for name, rows in tables.items()}


def main() -> int:
    cfg = config.load()
    try:
        counts = export(cfg)
    except ExportError as e:
        print(f"Could not read the shop database: {e}", file=sys.stderr)
        return 1
    print(f"snapshot: {cfg.snapshot_path}")
    print("  " + "  ".join(f"{name}: {n:,}" for name, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
