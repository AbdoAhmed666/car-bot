# ELYASSER (الياسر): notes on the program's database

What car-bot reads, and what was learned about it on the real shop's data.
Everything here is read-only; the queries live in `src/export.py`.

## Where the data is (found 2026-09-26)

- Program: **ELYASSER** (الياسر) on SQL Server 2008 SP1 Express.
- The data lives in an `.MDF` file in the program's folder (~41 MB, since
  2025-06). The program opens it with `AttachDbFilename=...;User Instance=True`,
  so it is **not** on the main `SQLEXPRESS` instance: it sits in a private
  instance that runs only while the program is open (and a while after).

What the probe showed on the real data (2026-09-26 copy):

- `Item.net_balance` (= `CurrentBalance0`) is the stock: it matches the
  `Item_store` ledger for all 1,104 items.
- `Sal_Invoice.Profit` and `Total` are net of `cashDiscount` (all 164
  invoices of the last 30 days). Returns carry negative profit.
- Every sale line is `unit` 0 (big unit); no item uses the other units.
- `pdate` is typed by hand: invoices entered on the 22nd were dated the 24th.
  The real entry time is `Tree_Account.Timee`. Hence reports go by invoice id.
- Sales are entered from 11:00 until after midnight; Fridays closed.
- `Minimum` and `Day_Recession` are unused (0 everywhere); categories
  (`Z_TypeItem1`) cover only 50 items. 88% of sales are on credit.
- What a customer owes is `SUM(debt - credit)` over their account in
  `Tree_Account`: it equals the program's own `CustBalance` for the 15
  biggest (tools/check_balances.py, 2026-09-27). The running `balance`
  column does not (17 of 144 differ): entries are not stored in date order.
  `Tree.Begin_balance` is not part of it. A payment is an entry with
  `id_CashCome`.

Tables that matter:

| table | what it is |
|---|---|
| `Item` | items: `ARname`, `InternationalCode`, `cost`/`PurchasePrice`, `BigPr0` (sale price), `CurrentBalance0`/`net_balance` (stock), `Minimum`, `IdTypeItem1` -> `Z_TypeItem1` (category), `Deleted` |
| `Sal_Invoice` / `Sal_Details` | sales: header (`pdate`, `id_cust`, `Total`, `Profit`) and lines (`id_item`, `unit`, `qu`, `pr`, `total_item`, `profit`) |
| `Rsal_invoice` / `Rsal_details` | sales returns (negative profit) |
| `Pur_Invoice` / `Pur_Details`, `RPur_*` | purchases and purchase returns |
| `Item_store` | stock ledger: every in/out movement with its date and source document (`come_big`/`out_big`; `id_pur` for a purchase, `id_sal`, `id_rsal`, `id_rpur`). Purchases give each item's first and last arrival, so goods just in are not called idle |
| `Sal_Deleted` | lines deleted from sales invoices |
| `cust`, `Tree`, `Tree_Account` | customers/suppliers, their accounts, and every account entry (`debt`, `credit`, `id_sal` for a sale, `id_CashCome` for a payment) |

`sal_temp` / `pur_temp` are the program's entry scratch tables - ignore them.
`unit` is 0/1/2 (big/middle/small, converted with `CountMiddel`/`CountSmall`).

Rules for the queries on it (all in `src/export.py`):

- **SELECT only**, with `WITH (NOLOCK)` so the program never waits on us.
- **Must run on SQL Server 2008**: no `IIF`, `FORMAT`, `CONCAT`, `TRY_CAST`,
  `STRING_AGG`, `OFFSET/FETCH`. `tests/test_sql_rules.py` checks both.
- On the shop PC the export runs as the **same Windows user** as the
  program. Another user would start a second private instance and fight the
  program for the MDF file.

## Tools (read-only on the shop's data)

- `tools/discover.ps1` - map of the shop PC's SQL Server: instances (including
  the program's private one), tables, columns, database files, connection strings.
- `tools/backup.ps1` - verified `COPY_ONLY` backup of the program's database, on the shop PC.
- `tools/restore.ps1` - restores that backup on the laptop as `ELyasserDB`.
  Never take it back to the shop PC: the newer SQL Server upgrades it.
- `tools/probe.ps1` - the checks the design rests on, on the restored copy.
- `tools/check_balances.py` - how to compute what customers owe, compared with the program.
- `tools/install_sync.ps1` - the sync task on the shop PC (at logon and every 30 minutes).
