"""A made-up shop in the ELYASSER tables, for testing without the real data.

Item names are real ELYASSER item names; customer names and every number are
invented, shaped like the shop (see tools/probe.ps1): credit-heavy invoices,
profit net of the cash discount, Fridays closed, big units only. Items and
customers follow profiles, so the reports have known answers:

    ANCHOR (2026-09-26) is "today". On it: an item runs out, one sells below
    cost, a line is deleted and a return comes in. Two customers stopped
    buying a while ago; one is new. One keeps buying on credit but stopped
    paying 50 days ago.
"""
import math
import random
from datetime import datetime, timedelta

ANCHOR = datetime(2026, 9, 26)
EXPORTED_AT = ANCHOR + timedelta(hours=18)
DAYS = 330

# made-up costs: the list's figures, moved by these factors so none is the shop's own
COST_SHIFT = (1.13, 0.88, 1.21, 0.93, 1.07, 0.81, 1.17)

# name, cost, sales per day, final stock, profile
# profiles: sells | idle:<days since last sale> | never | cheap (price under cost) | deleted
ITEMS = [
    ("فلتر تكييف نيوالينترا", 55, 3.5, 12, "sells"),            # ~3 days of stock: running low
    ("قلب طلمبه بنزين هونداي HI-Q", 225, 3.2, 45, "sells"),
    ("موبينه سيراتو", 125, 2.5, 51, "sells"),
    ("حساس ايدل لانوس", 125, 1.8, 8, "sells"),                   # ~4 days: running low
    ("حساس ايدل لانوس GM كورى", 185, 1.04, 7, "sells"),           # ~7 days: running low
    ("طلمبه باور اوبترا", 1700, 0.7, 4, "sells"),                # ~6 days: running low
    ("طلمبه باور لانوس", 1675, 0.45, 17, "sells"),
    ("طلمبه باور نيو اوبترا", 1810, 0.18, 7, "sells"),
    ("طلمبه باور فيرنا", 1500, 0.2, 31, "sells"),
    ("طلمبه باور سيراتو", 1760, 0.12, 10, "sells"),
    ("طلمبه باور لانسر بومه", 1775, 0.11, 4, "sells"),
    ("طلمبه بنزين كامله اوبترا", 860, 0.23, 6, "sells"),
    ("طقم كوستبانات فيرنا", 1135, 0.55, 8, "sells"),
    ("كولر كامل كروز", 1115, 0.4, 4, "sells"),
    ("كوعه كاملة كروزبالثرموستات", 640, 0.4, 3, "sells"),
    ("زيت فتيس 4 سرعات", 350, 0.8, 0, "sells"),                 # out of stock, still in demand
    ("زيت فتيس 6 سرعات", 400, 0.53, 0, "sells"),
    ("ماستر فرامل عمومى لانوس", 600, 0.38, 1, "sells"),
    ("بلي عجل امامي لانوس HSC", 185, 1.9, 148, "sells"),
    ("حساس TBS لانوس", 80, 1.8, 86, "sells"),
    ("موبينه كرولا 1300", 325, 1.05, 39, "sells"),
    ("كويل لانوس", 700, 0.32, 0, "sells"),                      # runs out on ANCHOR
    ("فلتر زيت تويوتا", 60, 1.2, 60, "sells"),
    ("وش غطاء تاكيهات اوبترا", 700, 0.31, 3, "sells"),
    ("عصايه فتيس فيرنا", 230, 0.9, 32, "sells"),
    ("سيلكون المانى فكتور رانز", 78, 0.05, 450, "sells"),       # slow: stock for years
    ("بلي عجل امامي فيرنا", 300, 0.3, -3, "sells"),             # negative stock
    ("مشترك ريداتير كياسول بالغطاء", 130, 0.3, 23, "cheap"),    # priced under cost
    ("بلي عجل امامى لانسر قرش", 310, 0.2, 29, "idle:145"),
    ("تيش ميزان خلفي بوما        CTR", 158.19, 0.3, 52, "idle:171"),   # padded name, as in ELYASSER
    ("بلف كمبروسر RB", 658.33, 0.15, 12, "idle:105"),
    ("جوان وش سلندر كروز", 290, 0.2, 26, "idle:257"),
    ("اويل سيل صباب لانسر", 95, 0.3, 37, "idle:300"),
    ("خرطوم تكيف سيراتو 2015", 300, 0.0, 10, "never"),
    ("طقم تيل امامي سيراتو", 450, 0.0, 0, "never"),
    ("مساعدين امامي كروز", 520, 0.0, 12, "new:10"),             # arrived 10 days ago, no sale yet: not idle
    ("صنف قديم ممسوح", 10, 0.2, 5, "deleted"),
]

# name, share of invoices, profile: steady | stopped:<days ago> | new:<days ago> | cash | supplier
# The names are invented (only the walk-in "cash" account is the program's own name):
# never put a real customer's name here, it ends up in screenshots and docs.
CUSTOMERS = [
    ("نقــــدى", 3, "cash"),                      # walk-in cash sales
    ("مركز النجمة", 6, "steady"),
    ("ورشة الفجر", 5, "steady"),
    ("معرض الشروق", 4, "steady"),
    ("مؤسسة التوفيق", 3, "steady"),
    ("ورشة الأمانة", 3, "stopped:40"),            # was buying every few days, then stopped
    ("مركز الإخلاص", 2, "stopped:75"),
    ("مؤسسة النور", 2, "steady"),
    ("معرض الوفاء", 2, "steady"),
    ("مركز الرحمة", 2, "steady"),
    ("معرض السعادة", 1, "steady"),
    ("مركز الهدى", 2, "new:20"),                   # first bought 20 days ago
    ("مورد قطع غيار", 0, "supplier"),              # sells to the shop, never buys
]
STOPPED_PAYING = {"مؤسسة التوفيق": 50}               # still buys, last paid this many days ago
# every 10 days a customer pays about this share of what they owe: 0.3 brings the money back
# in about 5 weeks; the slow one keeps about 13 weeks of purchases, though he pays regularly
PAY_SHARE = {"معرض الشروق": 0.11}
CASH_ACCOUNT = 26                                 # "الدرج": not a customer account


def _poisson(rng, lam):
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def build(seed=42) -> dict:
    """Rows of every ELYASSER table, as {table: [ {column: value} ]}."""
    rng = random.Random(seed)
    items = []
    for n, (name, cost, rate, stock, profile) in enumerate(ITEMS, 1):
        cost = round(cost * COST_SHIFT[n % len(COST_SHIFT)] / 5) * 5      # not the shop's real costs
        price = round(cost * (0.92 if profile == "cheap" else 1.3) / 5) * 5
        last_day = ANCHOR - timedelta(days=int(profile.split(":")[1])) if profile.startswith("idle") else ANCHOR
        items.append({"id": n, "name": name, "cost": cost, "price": price, "rate": rate, "stock": stock,
                      "profile": profile, "last_day": last_day})
    by_name = {" ".join(i["name"].split()): i for i in items}

    customers = []
    for n, (name, share, profile) in enumerate(CUSTOMERS, 2):
        first, last = ANCHOR - timedelta(days=DAYS), ANCHOR
        if profile.startswith("stopped"):
            last = ANCHOR - timedelta(days=int(profile.split(":")[1]))
        if profile.startswith("new"):
            first = ANCHOR - timedelta(days=int(profile.split(":")[1]))
        customers.append({"id": n, "name": name, "share": share, "profile": profile, "first": first,
                          "last": last, "account": 1000 + n})
    walk_in = customers[0]

    t = {k: [] for k in ["Sal_Invoice", "Sal_Details", "Rsal_invoice", "Rsal_details", "Sal_Deleted",
                         "Tree_Account"]}
    ids = {"sal": 0, "line": 0, "ret": 0, "ret_line": 0, "del": 0, "ledger": 0, "cash": 0}

    running = {}

    def ledger(account, when, debt=0.0, credit=0.0, payment=False):
        ids["ledger"] += 1
        running[account] = round(running.get(account, 0.0) + debt - credit, 2)
        if payment:
            ids["cash"] += 1
        t["Tree_Account"].append({"id": ids["ledger"], "id_Account": account, "pdate": when, "des": "",
                                  "debt": debt, "credit": credit, "balance": running[account], "id_sal": 0,
                                  "Timee": when, "id_CashCome": ids["cash"] if payment else None})

    def pick_customer(day, rng=rng):
        live = [c for c in customers if c["share"] and c["first"] <= day <= c["last"]]
        return rng.choices(live, weights=[c["share"] for c in live])[0]

    def add_invoice(when, picks, customer, credit=None, discount=None):
        ids["sal"] += 1
        total = profit = 0.0
        for item, qty, price in picks:
            ids["line"] += 1
            line_total, line_profit = qty * price, qty * (price - item["cost"])
            t["Sal_Details"].append({"id": ids["line"], "id_sal": ids["sal"], "id_item": item["id"], "unit": 0,
                                     "qu": float(qty), "pr": float(price), "Discount": 0, "total_item": line_total,
                                     "profit": line_profit, "id_store": 20})
            total += line_total
            profit += line_profit
        if customer is walk_in:
            credit = False
        credit = rng.random() < 0.85 if credit is None else credit
        if discount is None:
            discount = round(total * 0.05 / 5) * 5 if rng.random() < 0.2 else 0
        t["Sal_Invoice"].append({"id_sal": ids["sal"], "id_store": 20, "id_cust": customer["id"], "pdate": when,
                                 "cashDiscount": discount, "AmountPaid": 0 if credit else total - discount,
                                 "Total": total - discount, "TypePaied": 1 if credit else 0,
                                 "Profit": profit - discount})
        if credit:
            ledger(customer["account"], when, debt=total - discount)
        else:
            ledger(CASH_ACCOUNT, when, debt=total - discount)
        return ids["sal"]

    for back in range(DAYS, -1, -1):
        day = ANCHOR - timedelta(days=back)
        if day.weekday() == 4:          # Friday: closed
            continue
        pool = []
        for item in items:
            if item["profile"] == "never" or day > item["last_day"]:
                continue
            pool += [item] * _poisson(rng, item["rate"])
        rng.shuffle(pool)
        while pool:
            size = min(len(pool), rng.randint(1, 4))
            picks, pool = pool[:size], pool[size:]
            hour = rng.choice([11, 12, 13, 14, 15, 15, 16, 16, 17, 17, 18, 19, 20, 21, 22, 23, 0])
            when = day + timedelta(hours=hour, minutes=rng.randint(0, 59))
            add_invoice(when, [(i, 1, i["price"]) for i in picks], pick_customer(day))

        if rng.random() < 0.3:          # a line deleted from an invoice now and then
            ids["del"] += 1
            item = rng.choice(items[:25])
            t["Sal_Deleted"].append({"id": ids["del"], "id_sal": max(ids["sal"], 1), "ARname": item["name"],
                                     "UnitName": "وحدة كبرى", "qu": 1.0, "pr": item["price"],
                                     "pdate": day + timedelta(hours=15), "Cust_Name": pick_customer(day)["name"]})
        if back % 7 == 3 and ids["sal"]:    # a return about once a week
            ids["ret"] += 1
            ids["ret_line"] += 1
            item = rng.choice(items[:25])
            t["Rsal_invoice"].append({"id_Rsal": ids["ret"], "id_store": 20, "id_cust": pick_customer(day)["id"],
                                      "pdate": day + timedelta(hours=12), "Total": item["price"],
                                      "Profit": -(item["price"] - item["cost"])})
            t["Rsal_details"].append({"id": ids["ret_line"], "id_RSal": ids["ret"], "id_item": item["id"], "unit": 0,
                                      "qu": 1.0, "pr": item["price"], "total_item": item["price"],
                                      "Profit": -(item["price"] - item["cost"])})
        if back % 10 == 0:              # customers pay part of what they owe
            for c in customers[1:]:
                if c["share"] and c["first"] <= day <= c["last"]:
                    owed = max(running.get(c["account"], 0.0), 0.0)
                    amount = round(owed * PAY_SHARE.get(c["name"], 0.3) * rng.uniform(2000, 15000) / 8500, -2)
                    if amount > 0 and back >= STOPPED_PAYING.get(c["name"], 0):
                        ledger(c["account"], day + timedelta(hours=19), credit=amount, payment=True)

    # ANCHOR: the day the end-of-day report is tested on
    today = ANCHOR + timedelta(hours=13)
    kings = customers[1]
    add_invoice(today, [(by_name["كويل لانوس"], 2, by_name["كويل لانوس"]["price"]),
                        (by_name["حساس ايدل لانوس"], 3, by_name["حساس ايدل لانوس"]["price"])],
                kings, credit=True, discount=0)
    cheap = by_name["مشترك ريداتير كياسول بالغطاء"]
    add_invoice(today + timedelta(hours=2), [(cheap, 2, cheap["price"])], walk_in, credit=False, discount=0)
    ids["del"] += 1
    t["Sal_Deleted"].append({"id": ids["del"], "id_sal": ids["sal"], "ARname": "فلتر زيت تويوتا", "UnitName": "وحدة كبرى",
                             "qu": 2.0, "pr": 90.0, "pdate": today + timedelta(hours=3), "Cust_Name": "ورشة الفجر"})
    mob = by_name["موبينه سيراتو"]
    ids["ret"] += 1
    ids["ret_line"] += 1
    t["Rsal_invoice"].append({"id_Rsal": ids["ret"], "id_store": 20, "id_cust": kings["id"], "pdate": today + timedelta(hours=4),
                              "Total": mob["price"], "Profit": -(mob["price"] - mob["cost"])})
    t["Rsal_details"].append({"id": ids["ret_line"], "id_RSal": ids["ret"], "id_item": mob["id"], "unit": 0, "qu": 1.0,
                              "pr": mob["price"], "total_item": mob["price"], "Profit": -(mob["price"] - mob["cost"])})

    # the stock ledger: every item came in when the shop started; the ones still selling were
    # restocked 25 days ago; the new one arrived 10 days ago. A customer return and a sale also
    # move stock but are not arrivals from a supplier.
    t["Item_store"] = []

    def movement(item, when, come=0.0, out=0.0, pur=None, rsal=None, sal=None):
        t["Item_store"].append({"id": len(t["Item_store"]) + 1, "id_item": item["id"], "id_store": 20,
                                "come_big": come, "out_big": out, "pdate": when, "id_pur": pur,
                                "id_rsal": rsal, "id_sal": sal})

    start = ANCHOR - timedelta(days=DAYS + 5)
    for item in items:
        if item["profile"].startswith("new"):
            movement(item, ANCHOR - timedelta(days=int(item["profile"].split(":")[1]), hours=-11), come=item["stock"],
                     pur=500 + item["id"])
            continue
        movement(item, start, come=max(item["stock"], 0) + 50, pur=item["id"])
        if item["profile"] == "sells":
            movement(item, ANCHOR - timedelta(days=25, hours=-12), come=10, pur=300 + item["id"])
    idle_item = next(i for i in items if i["profile"].startswith("idle"))
    movement(idle_item, ANCHOR - timedelta(days=5), come=1, pur=0, rsal=1)      # a return: not an arrival
    movement(idle_item, ANCHOR - timedelta(days=200), out=1, sal=1)             # a sale: not an arrival

    t["Item"] = [{"id_item": i["id"], "ARname": i["name"], "InternationalCode": f"0{1000 + i['id']}",
                  "IdTypeItem1": 1, "PurchasePrice": i["cost"], "BigPr0": i["price"], "Minimum": 0,
                  "Day_Recession": 0, "CountMiddel": 1, "CountSmall": 1, "Balance": 0, "CurrentBalance0": i["stock"],
                  "cost": i["cost"], "net_balance": i["stock"], "Deleted": i["profile"] == "deleted",
                  "DateEdit": ANCHOR.date(), "DateCreate": datetime(2025, 6, 14).date()} for i in items]
    t["cust"] = [{"id_cust": c["id"], "Aname": c["name"], "Mobile": "01000000000",
                  "IsCustomer": 0 if c["profile"] in ("cash", "supplier") else 1, "id_account": c["account"],
                  "credit_limit": 50000.0, "MaxDayOfCredit": 30, "Deleted": False} for c in customers]
    t["Tree"] = ([{"id": c["account"], "aname": c["name"], "Begin_balance": 0} for c in customers]
                 + [{"id": CASH_ACCOUNT, "aname": "الدرج", "Begin_balance": 0}])
    return t


# ELYASSER table -> the snapshot table src/export.py fills from it
SNAPSHOT_TABLE = {"Item": "items", "cust": "customers", "Sal_Invoice": "invoices", "Sal_Details": "invoice_lines",
                  "Rsal_invoice": "returns", "Rsal_details": "return_lines", "Sal_Deleted": "deleted_lines",
                  "Tree": "accounts", "Tree_Account": "ledger", "Item_store": "arrivals"}


def source_rows(seed=42) -> dict:
    """What src/export.py's queries return from these tables, keyed by snapshot table."""
    t = build(seed)
    customer_accounts = {c["id_account"] for c in t["cust"]}
    t["Tree"] = [r for r in t["Tree"] if r["id"] in customer_accounts]
    t["Tree_Account"] = [r for r in t["Tree_Account"] if r["id_Account"] in customer_accounts]
    arrivals = {}
    for r in t["Item_store"]:                   # what the arrivals query groups, done here
        if (r["come_big"] or 0) > 0 and r["id_pur"]:
            first, last = arrivals.get(r["id_item"], (r["pdate"], r["pdate"]))
            arrivals[r["id_item"]] = (min(first, r["pdate"]), max(last, r["pdate"]))
    t["Item_store"] = [{"id_item": k, "first_in": a, "last_in": b} for k, (a, b) in arrivals.items()]
    return {SNAPSHOT_TABLE[name]: rows for name, rows in t.items()}


def snapshot(path, seed=42, forecasts=True):
    """Write the fake shop as the snapshot the bot reads (with the demand forecast, as the export does)."""
    from src import export
    tables, meta = export.transform(source_rows(seed)), {}
    if forecasts:
        tables, meta = export.with_forecasts(tables, EXPORTED_AT)
    return export.write_snapshot(tables, path, exported_at=EXPORTED_AT, meta=meta)


def load(conn, seed=42):
    """Insert the fake shop into the replica tables of an open pyodbc connection."""
    cur = conn.cursor()
    cur.fast_executemany = True
    for table, rows in build(seed).items():
        cols = list(rows[0])
        cur.executemany(f"INSERT INTO dbo.{table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
    conn.commit()
