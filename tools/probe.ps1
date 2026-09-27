<#
Answers the questions the bot's design depends on, from the restored copy of
the shop database on the dev laptop. Read-only.

Run in a PowerShell window, in the folder with this script:
  powershell -NoProfile -ExecutionPolicy Bypass -File .\probe.ps1

Writes probe.txt next to this script: totals, sales per day and hour, item
names of best sellers and idle stock. No customer names or phone numbers.
#>
param(
    [string]$Server = ".\SQLEXPRESS",
    [string]$User = "",          # empty = log in with the Windows account
    [string]$Password = "",
    [string]$Database = "ELyasserDB"
)

$ErrorActionPreference = "Stop"
$outPath = Join-Path $PSScriptRoot "probe.txt"
$out = New-Object System.Collections.Generic.List[string]


function Open-Db([string]$srv, [string]$db) {
    $b = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
    $b["Data Source"] = $srv
    $b["Initial Catalog"] = $db
    if ($User) {
        $b["User ID"] = $User
        $b["Password"] = $Password
    } else {
        $b["Integrated Security"] = $true
    }
    $b["Connect Timeout"] = 15
    $b["Application Name"] = "car-bot-probe"
    $conn = New-Object System.Data.SqlClient.SqlConnection $b.ConnectionString
    $conn.Open()
    $conn
}

function Invoke-Sql($conn, [string]$sql, [hashtable]$params = @{}) {
    $cmd = $conn.CreateCommand()
    $cmd.CommandText = "SET NOCOUNT ON; " + $sql
    $cmd.CommandTimeout = 300
    foreach ($k in $params.Keys) { [void]$cmd.Parameters.AddWithValue($k, $params[$k]) }
    $adapter = New-Object System.Data.SqlClient.SqlDataAdapter $cmd
    $table = New-Object System.Data.DataTable
    [void]$adapter.Fill($table)
    , $table
}

function Format-Value($v) {
    if ($null -eq $v -or $v -is [System.DBNull]) { return "-" }
    if ($v -is [datetime]) {
        if ($v.TimeOfDay.Ticks -eq 0) { return $v.ToString("yyyy-MM-dd") }
        return $v.ToString("yyyy-MM-dd HH:mm")
    }
    if ($v -is [double] -or $v -is [single] -or $v -is [decimal]) {
        return ([double]$v).ToString("0.##", [System.Globalization.CultureInfo]::InvariantCulture)
    }
    $s = ([string]$v) -replace "\s+", " "
    if ($s.Length -gt 50) { $s = $s.Substring(0, 50) + "..." }
    $s
}

function Add-Query([string]$title, [string]$sql) {
    $out.Add("")
    $out.Add("== $title ==")
    try {
        $t = Invoke-Sql $conn $sql @{ "@last" = $last }
        $out.Add("  " + (($t.Columns | ForEach-Object { $_.ColumnName }) -join " | "))
        foreach ($row in $t.Rows) {
            $out.Add("  " + (($row.ItemArray | ForEach-Object { Format-Value $_ }) -join " | "))
        }
        if (-not $t.Rows.Count) { $out.Add("  (no rows)") }
    } catch {
        $out.Add("  (failed: $($_.Exception.Message))")
    }
}

function Stop-WithMessage([string]$msg) {
    Write-Host ""
    Write-Host $msg -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}


try {
    Write-Host "Connecting to $Server / $Database ..."
    $conn = Open-Db $Server $Database
    # "now" = the last sale in the copy, so the numbers make sense on an old backup
    $last = [datetime](Invoke-Sql $conn "SELECT MAX(pdate) AS m FROM dbo.Sal_Invoice").Rows[0].m
} catch {
    Stop-WithMessage ("Could not read $Database on $Server.`n" + $_.Exception.Message)
}

$out.Add("car-bot probe  " + (Get-Date -Format "yyyy-MM-dd HH:mm") + "  |  last sale in the copy: " + $last.ToString("yyyy-MM-dd HH:mm"))
Write-Host "Running checks ..."

Add-Query "Overview" @'
SELECT (SELECT COUNT(*) FROM dbo.Sal_Invoice) AS invoices,
       (SELECT MIN(pdate) FROM dbo.Sal_Invoice) AS first_sale,
       (SELECT COUNT(*) FROM dbo.Sal_Details) AS sale_lines,
       (SELECT COUNT(*) FROM dbo.sal_temp) AS sal_temp_lines,
       (SELECT COUNT(*) FROM dbo.Item WHERE ISNULL(Deleted, 0) = 0) AS active_items,
       (SELECT COUNT(*) FROM dbo.Item WHERE Deleted = 1) AS deleted_items,
       (SELECT compatibility_level FROM sys.databases WHERE name = DB_NAME()) AS compat_level
'@

# which clock is real: the invoice date, the ledger's entry time, or sal_temp's?
Add-Query "Latest 15 invoices: pdate vs ledger entry time vs sal_temp time" @'
SELECT TOP 15 s.id_sal, s.pdate,
       (SELECT MIN(t.Timee) FROM dbo.Tree_Account t WHERE t.id_sal = s.id_sal) AS ledger_time,
       (SELECT MAX(x.pdate) FROM dbo.sal_temp x WHERE x.id_sal = s.id_sal) AS sal_temp_time,
       s.TypePaied, s.Total, s.cashDiscount, s.Profit
FROM dbo.Sal_Invoice s
ORDER BY s.id_sal DESC
'@

Add-Query "Invoices per hour of day, last 90 days (by pdate)" @'
SELECT DATEPART(hour, pdate) AS hour, COUNT(*) AS invoices
FROM dbo.Sal_Invoice
WHERE pdate >= DATEADD(day, -90, @last)
GROUP BY DATEPART(hour, pdate)
ORDER BY hour
'@

Add-Query "Sales entered per hour of day, last 90 days (by ledger Timee)" @'
SELECT DATEPART(hour, t.Timee) AS hour, COUNT(DISTINCT t.id_sal) AS invoices
FROM dbo.Tree_Account t
WHERE t.id_sal > 0 AND t.Timee >= DATEADD(day, -90, @last)
GROUP BY DATEPART(hour, t.Timee)
ORDER BY hour
'@

Add-Query "Program sessions (JopTime), latest 15" @'
SELECT TOP 15 pdate, BeginJop, EndJop FROM dbo.JopTime ORDER BY id DESC
'@

Add-Query "Sales per day, last 30 days" @'
SELECT CONVERT(char(10), pdate, 120) AS day, COUNT(*) AS invoices,
       SUM(Total) AS total, SUM(Profit) AS profit, SUM(cashDiscount) AS discount
FROM dbo.Sal_Invoice
WHERE pdate >= DATEADD(day, -30, @last)
GROUP BY CONVERT(char(10), pdate, 120)
ORDER BY day
'@

Add-Query "Returns and deleted lines per day, last 30 days" @'
SELECT d.day,
       (SELECT COUNT(*) FROM dbo.Rsal_invoice r WHERE CONVERT(char(10), r.pdate, 120) = d.day) AS returns,
       (SELECT SUM(r.Total) FROM dbo.Rsal_invoice r WHERE CONVERT(char(10), r.pdate, 120) = d.day) AS returned_total,
       (SELECT COUNT(*) FROM dbo.Sal_Deleted x WHERE CONVERT(char(10), x.pdate, 120) = d.day) AS deleted_lines
FROM (SELECT DISTINCT CONVERT(char(10), pdate, 120) AS day FROM dbo.Sal_Invoice
      WHERE pdate >= DATEADD(day, -30, @last)) d
ORDER BY d.day
'@

Add-Query "Payment type (TypePaied), last 90 days" @'
SELECT TypePaied, COUNT(*) AS invoices, SUM(Total) AS total, SUM(AmountPaid) AS paid
FROM dbo.Sal_Invoice
WHERE pdate >= DATEADD(day, -90, @last)
GROUP BY TypePaied
ORDER BY TypePaied
'@

# does the invoice header's Profit/Total agree with its lines, before or after the cash discount?
Add-Query "Invoice header vs lines, last 30 days" @'
SELECT COUNT(*) AS invoices,
  SUM(CASE WHEN ABS(ISNULL(s.Profit, 0) - ISNULL(d.p, 0)) < 1 THEN 1 ELSE 0 END) AS profit_eq_lines,
  SUM(CASE WHEN ABS(ISNULL(s.Profit, 0) - (ISNULL(d.p, 0) - ISNULL(s.cashDiscount, 0))) < 1 THEN 1 ELSE 0 END) AS profit_eq_lines_minus_disc,
  SUM(CASE WHEN ABS(ISNULL(s.Total, 0) - ISNULL(d.t, 0)) < 1 THEN 1 ELSE 0 END) AS total_eq_lines,
  SUM(CASE WHEN ABS(ISNULL(s.Total, 0) - (ISNULL(d.t, 0) - ISNULL(s.cashDiscount, 0))) < 1 THEN 1 ELSE 0 END) AS total_eq_lines_minus_disc
FROM dbo.Sal_Invoice s
LEFT JOIN (SELECT id_sal, SUM(profit) AS p, SUM(total_item) AS t FROM dbo.Sal_Details GROUP BY id_sal) d
       ON d.id_sal = s.id_sal
WHERE s.pdate >= DATEADD(day, -30, @last)
'@

Add-Query "Units used in sale lines (0 = big)" @'
SELECT unit, COUNT(*) AS lines FROM dbo.Sal_Details GROUP BY unit ORDER BY unit
'@

# which Item column is the real stock: compare each with the Item_store ledger
Add-Query "Stock columns vs the Item_store ledger (active items)" @'
SELECT COUNT(*) AS items,
  SUM(CASE WHEN ABS(ISNULL(i.CurrentBalance0, 0) - ISNULL(l.bal, 0)) < 0.001 THEN 1 ELSE 0 END) AS CurrentBalance0_ok,
  SUM(CASE WHEN ABS(ISNULL(i.net_balance, 0) - ISNULL(l.bal, 0)) < 0.001 THEN 1 ELSE 0 END) AS net_balance_ok,
  SUM(CASE WHEN ABS(ISNULL(i.Balance, 0) - ISNULL(l.bal, 0)) < 0.001 THEN 1 ELSE 0 END) AS Balance_ok,
  SUM(CASE WHEN ISNULL(i.net_balance, 0) > 0 THEN 1 ELSE 0 END) AS in_stock,
  SUM(CASE WHEN ISNULL(i.net_balance, 0) < 0 THEN 1 ELSE 0 END) AS negative_stock,
  SUM(CASE WHEN ISNULL(i.CountMiddel, 1) <> 1 OR ISNULL(i.CountSmall, 1) <> 1 THEN 1 ELSE 0 END) AS multi_unit_items
FROM dbo.Item i
LEFT JOIN (SELECT id_item, SUM(ISNULL(come_big, 0) - ISNULL(out_big, 0)) AS bal
           FROM dbo.Item_store GROUP BY id_item) l ON l.id_item = i.id_item
WHERE ISNULL(i.Deleted, 0) = 0
'@

Add-Query "Items where net_balance and the ledger disagree (first 10)" @'
SELECT TOP 10 i.id_item, i.ARname, i.CurrentBalance0, i.net_balance, i.Balance,
       l.big AS ledger_big, l.mid AS ledger_mid, l.small AS ledger_small, i.CountMiddel, i.CountSmall
FROM dbo.Item i
LEFT JOIN (SELECT id_item, SUM(ISNULL(come_big, 0) - ISNULL(out_big, 0)) AS big,
                  SUM(ISNULL(come_Middel, 0) - ISNULL(out_Middel, 0)) AS mid,
                  SUM(ISNULL(come_Small, 0) - ISNULL(out_Small, 0)) AS small
           FROM dbo.Item_store GROUP BY id_item) l ON l.id_item = i.id_item
WHERE ISNULL(i.Deleted, 0) = 0 AND ABS(ISNULL(i.net_balance, 0) - ISNULL(l.big, 0)) >= 0.001
ORDER BY i.id_item
'@

Add-Query "Item prices, cost and reorder fields (active items)" @'
SELECT SUM(CASE WHEN ISNULL(cost, 0) > 0 THEN 1 ELSE 0 END) AS with_cost,
       SUM(CASE WHEN ISNULL(cost, 0) = 0 THEN 1 ELSE 0 END) AS without_cost,
       SUM(CASE WHEN ABS(ISNULL(PurchasePrice, 0) - ISNULL(cost, 0)) >= 0.01 THEN 1 ELSE 0 END) AS cost_ne_purchase_price,
       SUM(CASE WHEN ISNULL(BigPr0, 0) > 0 AND BigPr0 < ISNULL(cost, 0) THEN 1 ELSE 0 END) AS price_below_cost,
       SUM(CASE WHEN ISNULL(Minimum, 0) > 0 THEN 1 ELSE 0 END) AS with_minimum,
       SUM(CASE WHEN ISNULL(Day_Recession, 0) > 0 THEN 1 ELSE 0 END) AS with_recession_days
FROM dbo.Item
WHERE ISNULL(Deleted, 0) = 0
'@

Add-Query "Categories (Z_TypeItem1)" @'
SELECT t.id, t.aname, COUNT(i.id_item) AS items
FROM dbo.Z_TypeItem1 t
LEFT JOIN dbo.Item i ON i.IdTypeItem1 = t.id AND ISNULL(i.Deleted, 0) = 0
GROUP BY t.id, t.aname
ORDER BY t.id
'@

Add-Query "Top 30 items by sales, last 90 days" @'
SELECT TOP 30 i.id_item, i.ARname, SUM(d.qu) AS qty, SUM(d.total_item) AS revenue,
       SUM(d.profit) AS profit, MAX(i.net_balance) AS stock_now
FROM dbo.Sal_Details d
JOIN dbo.Sal_Invoice s ON s.id_sal = d.id_sal
JOIN dbo.Item i ON i.id_item = d.id_item
WHERE s.pdate >= DATEADD(day, -90, @last)
GROUP BY i.id_item, i.ARname
ORDER BY revenue DESC
'@

Add-Query "Idle stock: in stock, no sale in 90 days (totals)" @'
SELECT COUNT(*) AS items, SUM(i.net_balance * i.cost) AS money_at_cost
FROM dbo.Item i
WHERE ISNULL(i.Deleted, 0) = 0 AND i.net_balance > 0
  AND NOT EXISTS (SELECT 1 FROM dbo.Sal_Details d JOIN dbo.Sal_Invoice s ON s.id_sal = d.id_sal
                  WHERE d.id_item = i.id_item AND s.pdate >= DATEADD(day, -90, @last))
'@

Add-Query "Idle stock: top 15 by money at cost" @'
SELECT TOP 15 i.id_item, i.ARname, i.net_balance AS stock, i.cost, i.net_balance * i.cost AS money_at_cost,
       (SELECT MAX(s.pdate) FROM dbo.Sal_Details d JOIN dbo.Sal_Invoice s ON s.id_sal = d.id_sal
        WHERE d.id_item = i.id_item) AS last_sale
FROM dbo.Item i
WHERE ISNULL(i.Deleted, 0) = 0 AND i.net_balance > 0
  AND NOT EXISTS (SELECT 1 FROM dbo.Sal_Details d JOIN dbo.Sal_Invoice s ON s.id_sal = d.id_sal
                  WHERE d.id_item = i.id_item AND s.pdate >= DATEADD(day, -90, @last))
ORDER BY money_at_cost DESC
'@

Add-Query "Program backup settings (ZZproperties)" @'
SELECT PathBackup, HourOfBackup, DataBaseName FROM dbo.ZZproperties
'@

$conn.Close()
[System.IO.File]::WriteAllLines($outPath, $out, (New-Object System.Text.UTF8Encoding $true))

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  $outPath"
Write-Host ""
Read-Host "Press Enter to close"
