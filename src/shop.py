"""The shop's data, read from the snapshot that src/export.py writes.

The bot never talks to the shop's SQL Server: it reads this SQLite file,
which the shop PC refreshes and sends while it is on. So the bot keeps
answering (from the latest copy) when the shop PC is off.
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class ShopUnavailable(Exception):
    """No snapshot to read yet, or it can't be opened."""


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    code: str
    stock: float
    price: float        # sale price, big unit
    cost: float         # the cost the program uses for its profit figures


@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    code: str = ""          # so customers can go through the same search as items


@dataclass
class ItemSales:
    qty: float = 0.0        # net of returns
    revenue: float = 0.0
    profit: float = 0.0
    invoices: int = 0


@dataclass(frozen=True)
class Period:
    """Which documents a report covers.

    Live reports go by document id ("everything entered since the last
    report"): the program's invoice dates are typed by hand and can run days
    ahead of when the invoice was entered. Simulations on an old copy go by
    invoice date instead.
    """
    after: dict = None          # {"sal": id, "rsal": id, "deleted": id}: strictly after these
    upto: dict = None           # ... and up to these, inclusive
    start: datetime = None
    end: datetime = None        # exclusive; None = open-ended


def _d(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _dt(text):
    return datetime.fromisoformat(text) if text else None


def _where(period, id_col, date_col, key):
    if period.after is not None:
        sql, params = f"{id_col} > ?", [period.after.get(key, 0)]
        if period.upto is not None:
            sql += f" AND {id_col} <= ?"
            params.append(period.upto.get(key, 0))
        return sql, params
    sql, params = f"{date_col} >= ?", [_d(period.start)]
    if period.end is not None:
        sql += f" AND {date_col} < ?"
        params.append(_d(period.end))
    return sql, params


class Shop:
    def __init__(self, cfg):
        self.path = Path(cfg.snapshot_path) if cfg is not None else None

    def _rows(self, sql, params=()) -> list:
        if not sql.lstrip().upper().startswith("SELECT"):
            raise ValueError("the bot only reads")
        if not self.path or not self.path.exists():
            raise ShopUnavailable(f"no snapshot at {self.path}: run python -m src.export")
        try:
            db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        except sqlite3.Error as e:
            raise ShopUnavailable(str(e)) from e
        try:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute(sql, list(params)).fetchall()]
        except sqlite3.Error as e:
            raise ShopUnavailable(str(e)) from e
        finally:
            db.close()

    def meta(self) -> dict:
        return {r["key"]: r["value"] for r in self._rows("SELECT key, value FROM meta")}

    def forecasts(self) -> dict:
        """{item id: pieces expected in the next 30 days}, only when the model beat the
        simple average in its backtest (src/forecast.py); otherwise empty."""
        if self.meta().get("forecast_used") != "1":
            return {}
        try:
            return {r["item_id"]: r["next_30"] for r in self._rows("SELECT item_id, next_30 FROM forecasts")}
        except ShopUnavailable:         # a snapshot from before forecasts existed
            return {}

    def exported_at(self):
        """When the shop PC last refreshed the data."""
        rows = self._rows("SELECT value FROM meta WHERE key = 'exported_at'")
        return _dt(rows[0]["value"]) if rows else None

    def items(self) -> list:
        return [Item(r["id"], r["name"], r["code"], r["stock"], r["price"], r["cost"])
                for r in self._rows("SELECT id, name, code, stock, price, cost FROM items WHERE deleted = 0")]

    def sales_by_item(self, start, end=None) -> dict:
        """{item id: ItemSales} for invoices dated in [start, end), returns subtracted."""
        params = [_d(start)] + ([_d(end)] if end else [])
        sold = self._rows(f"""
            SELECT l.item_id, SUM(l.qty) AS qty, SUM(l.total) AS revenue, SUM(l.profit) AS profit,
                   COUNT(DISTINCT l.invoice_id) AS invoices
            FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id
            WHERE i.date >= ?{" AND i.date < ?" if end else ""}
            GROUP BY l.item_id""", params)
        returned = self._rows(f"""
            SELECT l.item_id, SUM(l.qty) AS qty, SUM(l.total) AS revenue, SUM(l.profit) AS profit
            FROM return_lines l JOIN returns r ON r.id = l.return_id
            WHERE r.date >= ?{" AND r.date < ?" if end else ""}
            GROUP BY l.item_id""", params)
        out = {r["item_id"]: ItemSales(r["qty"], r["revenue"], r["profit"], r["invoices"]) for r in sold}
        for r in returned:
            s = out.setdefault(r["item_id"], ItemSales())
            s.qty -= r["qty"]
            s.revenue -= r["revenue"]
            s.profit += r["profit"]        # the program stores a return's profit as negative
        return out

    def last_sales(self, end=None) -> dict:
        """{item id: date of its latest sale}."""
        rows = self._rows(f"""
            SELECT l.item_id, MAX(i.date) AS last_sale
            FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id
            {"WHERE i.date < ?" if end else ""}
            GROUP BY l.item_id""", [_d(end)] if end else [])
        return {r["item_id"]: _dt(r["last_sale"]) for r in rows}

    def invoices(self, period) -> list:
        where, params = _where(period, "id", "date", "sal")
        rows = self._rows(f"""
            SELECT id, date, customer_id, total, profit, discount, credit FROM invoices
            WHERE {where} ORDER BY id""", params)
        return [{"id": r["id"], "date": _dt(r["date"]), "customer": r["customer_id"], "total": r["total"],
                 "profit": r["profit"], "discount": r["discount"], "credit": bool(r["credit"])} for r in rows]

    def sales_detail(self, period) -> list:
        """Every sale line in the period with its invoice, customer and item names, oldest invoice first."""
        where, params = _where(period, "i.id", "i.date", "sal")
        rows = self._rows(f"""
            SELECT i.id AS invoice, i.date, i.customer_id, i.credit, c.name AS customer, it.name AS item,
                   l.item_id, l.qty, l.price, l.total, l.profit
            FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id
            LEFT JOIN customers c ON c.id = i.customer_id
            LEFT JOIN items it ON it.id = l.item_id
            WHERE {where} ORDER BY i.id, l.id""", params)
        return [{**r, "date": _dt(r["date"]), "credit": bool(r["credit"]), "customer": r["customer"] or "",
                 "item": r["item"] or ""} for r in rows]

    def item_history(self, item_id, start=None, end=None, limit=5) -> dict:
        """Who bought this item: {"last": the latest sale lines (newest first), "buyers":
        [(customer, pieces)] since `start`, most first}."""
        cond = ["l.item_id = ?"] + (["i.date < ?"] if end else [])
        params = [item_id] + ([_d(end)] if end else [])
        last = self._rows(f"""
            SELECT i.id AS invoice, i.date, c.name AS customer, l.qty, l.price
            FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id
            LEFT JOIN customers c ON c.id = i.customer_id
            WHERE {" AND ".join(cond)} ORDER BY i.date DESC, i.id DESC LIMIT {int(limit)}""", params)
        if start:
            cond.append("i.date >= ?")
            params.append(_d(start))
        buyers = self._rows(f"""
            SELECT c.name AS customer, SUM(l.qty) AS qty
            FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id
            LEFT JOIN customers c ON c.id = i.customer_id
            WHERE {" AND ".join(cond)} GROUP BY i.customer_id ORDER BY qty DESC""", params)
        return {"last": [{**r, "date": _dt(r["date"]), "customer": r["customer"] or ""} for r in last],
                "buyers": [(r["customer"] or "", r["qty"]) for r in buyers if r["qty"] > 0]}

    def arrivals(self, end=None) -> dict:
        """{item id: (first, last) time stock came in from a supplier}; empty for a
        snapshot from before arrivals were exported. With `end`, what was known then
        (the latest arrival before it is not kept, so the first stands in for it)."""
        try:
            rows = self._rows("SELECT item_id, first_in, last_in FROM arrivals")
        except ShopUnavailable:
            return {}
        out = {}
        for r in rows:
            first, last = _dt(r["first_in"]), _dt(r["last_in"])
            if first and end and first >= end:
                continue
            if last and end and last >= end:
                last = first
            if first or last:
                out[r["item_id"]] = (first or last, last or first)
        return out

    def returns(self, period) -> list:
        where, params = _where(period, "id", "date", "rsal")
        rows = self._rows(f"SELECT id, date, customer_id, total, profit FROM returns WHERE {where} ORDER BY id",
                          params)
        return [{"id": r["id"], "date": _dt(r["date"]), "customer": r["customer_id"], "total": r["total"],
                 "profit": r["profit"]} for r in rows]

    def deleted_lines(self, period) -> list:
        """Lines removed from sales invoices after they were entered."""
        where, params = _where(period, "id", "date", "deleted")
        rows = self._rows(f"""
            SELECT id, invoice_id, item_name, qty, price, date, customer_name FROM deleted_lines
            WHERE {where} ORDER BY id""", params)
        return [{"id": r["id"], "invoice": r["invoice_id"], "name": r["item_name"], "qty": r["qty"],
                 "price": r["price"], "date": _dt(r["date"]), "customer": r["customer_name"]} for r in rows]

    def last_ids(self) -> dict:
        """Newest invoice, return and deleted-line ids: where the next report starts."""
        r = self._rows("""
            SELECT (SELECT MAX(id) FROM invoices) AS sal, (SELECT MAX(id) FROM returns) AS rsal,
                   (SELECT MAX(id) FROM deleted_lines) AS deleted""")[0]
        return {k: int(v or 0) for k, v in r.items()}

    def check(self) -> dict:
        """Quick look for "is this the right data?"."""
        r = self._rows("""
            SELECT (SELECT COUNT(*) FROM items WHERE deleted = 0) AS items,
                   (SELECT COUNT(*) FROM invoices) AS invoices,
                   (SELECT MAX(date) FROM invoices) AS last_invoice,
                   (SELECT COUNT(*) FROM customers WHERE deleted = 0) AS customers""")[0]
        r["exported_at"] = self.exported_at()
        return r

    # --- customers ---------------------------------------------------------------

    def customers(self) -> list:
        """Everyone who has bought at least once (suppliers in the same table never have)."""
        rows = self._rows("""
            SELECT id, name FROM customers
            WHERE deleted = 0 AND id IN (SELECT DISTINCT customer_id FROM invoices)""")
        return [Customer(r["id"], r["name"]) for r in rows]

    def customer_sales(self, start=None, end=None) -> dict:
        """{customer id: totals} for invoices dated in [start, end), returns subtracted."""
        where, params = ["1 = 1"], []
        if start:
            where.append("date >= ?")
            params.append(_d(start))
        if end:
            where.append("date < ?")
            params.append(_d(end))
        sold = self._rows(f"""
            SELECT customer_id, COUNT(*) AS invoices, SUM(total) AS total, SUM(profit) AS profit,
                   SUM(CASE WHEN credit = 1 THEN total ELSE 0 END) AS credit_total,
                   MIN(date) AS first_date, MAX(date) AS last_date
            FROM invoices WHERE {" AND ".join(where)} GROUP BY customer_id""", params)
        returned = self._rows(f"""
            SELECT customer_id, SUM(total) AS total, SUM(profit) AS profit
            FROM returns WHERE {" AND ".join(where)} GROUP BY customer_id""", params)
        out = {r["customer_id"]: {"invoices": r["invoices"], "total": r["total"], "profit": r["profit"],
                                  "credit_total": r["credit_total"], "returns": 0.0, "first": _dt(r["first_date"]),
                                  "last": _dt(r["last_date"])} for r in sold}
        for r in returned:
            if r["customer_id"] in out:
                out[r["customer_id"]]["total"] -= r["total"]
                out[r["customer_id"]]["profit"] += r["profit"]      # stored negative
                out[r["customer_id"]]["returns"] = r["total"]
        return out

    def purchase_days(self, end=None) -> dict:
        """{customer id: sorted list of the days they bought on}."""
        rows = self._rows(f"""
            SELECT customer_id, substr(date, 1, 10) AS day FROM invoices
            {"WHERE date < ?" if end else ""}
            GROUP BY customer_id, substr(date, 1, 10) ORDER BY customer_id, day""", [_d(end)] if end else [])
        out = {}
        for r in rows:
            out.setdefault(r["customer_id"], []).append(datetime.fromisoformat(r["day"]))
        return out

    def balances(self, end=None, since=None) -> dict:
        """{customer id: {"balance", "payments": [(date, amount)] oldest first,
        and from `since` on: "before" (the balance then), "bought" (taken on credit),
        "paid"}}.

        What a customer owes is the sum of debt - credit over their account's
        entries; it matches the program's own figure. Empty for a snapshot from
        before payments were marked."""
        params = [_d(since) if since else ""] * 3 + ([_d(end)] if end else [])
        try:
            owed = self._rows(f"""
                SELECT c.id, SUM(l.debt - l.credit) AS balance,
                       SUM(CASE WHEN l.date < ? THEN l.debt - l.credit ELSE 0 END) AS before,
                       SUM(CASE WHEN l.date >= ? THEN l.debt ELSE 0 END) AS bought,
                       SUM(CASE WHEN l.date >= ? AND l.payment = 1 THEN l.credit ELSE 0 END) AS paid
                FROM customers c JOIN ledger l ON l.account_id = c.account_id
                {"WHERE l.date < ?" if end else ""}
                GROUP BY c.id""", params)
            params = [_d(end)] if end else []
            paid = self._rows(f"""
                SELECT c.id, l.date, l.credit
                FROM customers c JOIN ledger l ON l.account_id = c.account_id
                WHERE l.payment = 1 AND l.credit > 0{" AND l.date < ?" if end else ""}
                ORDER BY c.id, l.date""", params)
        except ShopUnavailable:
            return {}
        out = {r["id"]: {"balance": r["balance"] or 0.0, "before": r["before"] or 0.0, "bought": r["bought"] or 0.0,
                         "paid": r["paid"] or 0.0, "payments": []} for r in owed}
        for r in paid:
            if r["id"] in out and r["date"]:
                out[r["id"]]["payments"].append((_dt(r["date"]), r["credit"]))
        return out

    def customer_items(self, customer_id, start=None, end=None, limit=5) -> list:
        """What this customer bought most in [start, end), by money; from the first
        invoice if no start: [(item name, pieces, total, last bought)]."""
        where = ["i.customer_id = ?"] + (["i.date >= ?"] if start else []) + (["i.date < ?"] if end else [])
        params = [customer_id] + ([_d(start)] if start else []) + ([_d(end)] if end else [])
        rows = self._rows(f"""
            SELECT it.name, SUM(l.qty) AS qty, SUM(l.total) AS total, MAX(i.date) AS last_date
            FROM invoice_lines l
            JOIN invoices i ON i.id = l.invoice_id
            JOIN items it ON it.id = l.item_id
            WHERE {" AND ".join(where)}
            GROUP BY it.name ORDER BY total DESC LIMIT {int(limit)}""", params)
        return [(r["name"], r["qty"], r["total"], _dt(r["last_date"])) for r in rows]

    def first_invoice(self, end=None):
        """When the program's records start."""
        rows = self._rows(f"SELECT MIN(date) AS d FROM invoices{' WHERE date < ?' if end else ''}",
                          [_d(end)] if end else [])
        return _dt(rows[0]["d"]) if rows else None
