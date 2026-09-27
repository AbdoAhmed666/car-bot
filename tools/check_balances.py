"""How much does each customer owe, and how do they pay? Compares ways of
computing it with the program's own figures, and lists the kinds of money
coming in, on the restored copy. Read-only.

    .venv\\Scripts\\python tools\\check_balances.py

Prints the result and writes balances.txt next to this script (send it back).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config, export  # noqa: E402

PER_CUSTOMER = """
    SELECT c.id_cust, c.Aname,
           ISNULL((SELECT SUM(a.debt - a.credit) FROM dbo.Tree_Account a WITH (NOLOCK)
                   WHERE a.id_Account = c.id_account), 0) AS ledger_sum,
           ISNULL((SELECT TOP 1 a.balance FROM dbo.Tree_Account a WITH (NOLOCK)
                   WHERE a.id_Account = c.id_account ORDER BY a.id DESC), 0) AS last_row_balance,
           ISNULL(t.Begin_balance, 0) AS begin_balance,
           (SELECT COUNT(*) FROM dbo.Tree_Account a WITH (NOLOCK) WHERE a.id_Account = c.id_account) AS entries
    FROM dbo.cust c WITH (NOLOCK)
    LEFT JOIN dbo.Tree t WITH (NOLOCK) ON t.id = c.id_account
    WHERE c.id_cust IN (SELECT s.id_cust FROM dbo.Sal_Invoice s WITH (NOLOCK))"""

QUERIES = [
    ("Summary (customers who bought)", f"""
        SELECT COUNT(*) AS customers,
               SUM(CASE WHEN ABS(x.ledger_sum - x.last_row_balance) < 1 THEN 1 ELSE 0 END) AS sum_eq_last_row,
               SUM(CASE WHEN ABS(x.ledger_sum + x.begin_balance - x.last_row_balance) < 1 THEN 1 ELSE 0 END)
                   AS sum_plus_begin_eq_last_row,
               SUM(CASE WHEN x.begin_balance <> 0 THEN 1 ELSE 0 END) AS with_begin_balance,
               SUM(CASE WHEN x.entries = 0 THEN 1 ELSE 0 END) AS no_ledger_entries,
               SUM(x.ledger_sum) AS total_ledger_sum, SUM(x.last_row_balance) AS total_last_row
        FROM ({PER_CUSTOMER}) x"""),
    ("Biggest 15 by ledger sum", f"""
        SELECT TOP 15 x.* FROM ({PER_CUSTOMER}) x ORDER BY x.ledger_sum DESC"""),
    ("15 where ledger sum and last row differ", f"""
        SELECT TOP 15 x.* FROM ({PER_CUSTOMER}) x
        WHERE ABS(x.ledger_sum - x.last_row_balance) >= 1 ORDER BY x.ledger_sum DESC"""),
    ("The program's CustBalance on each customer's latest invoice (15 biggest)", f"""
        SELECT TOP 15 x.Aname, x.ledger_sum, x.last_row_balance, v.CustBalance, v.pdate
        FROM ({PER_CUSTOMER}) x
        CROSS APPLY (SELECT TOP 1 vs.CustBalance, vs.pdate FROM dbo.View_SalInvoice vs WITH (NOLOCK)
                     WHERE vs.Cust_Name = x.Aname ORDER BY vs.pdate DESC) v
        ORDER BY x.ledger_sum DESC"""),
    ("All the columns of an account entry (the latest)", """
        SELECT TOP 1 * FROM dbo.Tree_Account WITH (NOLOCK) ORDER BY id DESC"""),
    ("Money in from customers that is not a cash receipt (id_CashCome empty): cheques? discounts?", """
        SELECT TOP 20 CASE WHEN a.id_sal IS NULL OR a.id_sal = 0 THEN 'no invoice' ELSE 'invoice' END AS linked,
               LEFT(CAST(a.des AS nvarchar(200)), 40) AS description, COUNT(*) AS entries, SUM(a.credit) AS credit
        FROM dbo.Tree_Account a WITH (NOLOCK)
        WHERE a.credit > 0 AND (a.id_CashCome IS NULL OR a.id_CashCome = 0)
          AND a.id_Account IN (SELECT c.id_account FROM dbo.cust c WITH (NOLOCK))
        GROUP BY CASE WHEN a.id_sal IS NULL OR a.id_sal = 0 THEN 'no invoice' ELSE 'invoice' END,
                 LEFT(CAST(a.des AS nvarchar(200)), 40)
        ORDER BY SUM(a.credit) DESC"""),
    ("Cash receipts from customers, for comparison", """
        SELECT COUNT(*) AS entries, SUM(a.credit) AS credit
        FROM dbo.Tree_Account a WITH (NOLOCK)
        WHERE a.credit > 0 AND a.id_CashCome IS NOT NULL AND a.id_CashCome <> 0
          AND a.id_Account IN (SELECT c.id_account FROM dbo.cust c WITH (NOLOCK))"""),
    ("What the entries of the biggest customer look like (latest 12)", f"""
        SELECT TOP 12 a.id, a.pdate, a.Timee, a.debt, a.credit, a.balance, a.id_sal, a.id_CashCome
        FROM dbo.Tree_Account a WITH (NOLOCK)
        WHERE a.id_Account = (SELECT TOP 1 c.id_account FROM dbo.cust c WITH (NOLOCK)
                              WHERE c.id_cust IN (SELECT s.id_cust FROM dbo.Sal_Invoice s WITH (NOLOCK))
                              ORDER BY (SELECT SUM(b.debt - b.credit) FROM dbo.Tree_Account b WITH (NOLOCK)
                                        WHERE b.id_Account = c.id_account) DESC)
        ORDER BY a.id DESC"""),
]


def fmt(v):
    if v is None:
        return "-"
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, float) or type(v).__name__ == "Decimal":
        return f"{float(v):,.2f}"
    return " ".join(str(v).split())


def main():
    cfg = config.load()
    conn = export.connect(cfg)
    out = []
    try:
        cur = conn.cursor()
        for title, sql in QUERIES:
            out += ["", f"== {title} =="]
            try:
                cur.execute(sql)
                cols = [c[0] for c in cur.description]
                out.append("  " + " | ".join(cols))
                out += ["  " + " | ".join(fmt(v) for v in row) for row in cur.fetchall()]
            except Exception as e:           # a view or column missing: keep going
                out.append(f"  (failed: {e})")
    finally:
        conn.close()
    text = "\n".join(out)
    path = Path(__file__).with_name("balances.txt")
    path.write_text(text + "\n", encoding="utf-8-sig")
    try:
        print(text)
    except UnicodeEncodeError:
        pass
    print(f"\nwritten: {path}")


if __name__ == "__main__":
    main()
