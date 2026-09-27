<#
Copies the shop program's database into a .bak file, for development on another PC.

Run on the shop PC, with the ELYASSER program OPEN:
  right-click this file -> "Run with PowerShell"

The .bak file is written next to this script, so run it from a USB stick and
the copy lands on the stick. The program keeps working while it runs.

BACKUP ... WITH COPY_ONLY only reads the database and does not interfere with
any backup routine the program has.
#>
param(
    [string]$Server = "",       # empty = the private SQL instance the program opened
    [string]$User = "",         # empty = log in with the Windows account
    [string]$Password = "",
    [string]$Database = "",     # empty = the biggest database on that server
    [string]$OutDir = ""        # empty = the folder this script is in
)

$ErrorActionPreference = "Stop"
if (-not $OutDir) { $OutDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$OutDir = [System.IO.Path]::GetFullPath($OutDir)


function Open-Db([string]$srv, [string]$db, [bool]$windowsLogin = $false) {
    $b = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
    $b["Data Source"] = $srv
    $b["Initial Catalog"] = $db
    if ($User -and -not $windowsLogin) {
        $b["User ID"] = $User
        $b["Password"] = $Password
    } else {
        $b["Integrated Security"] = $true
    }
    $b["Connect Timeout"] = 15
    $b["Application Name"] = "car-bot-backup"
    $conn = New-Object System.Data.SqlClient.SqlConnection $b.ConnectionString
    $conn.Open()
    $conn
}

function New-Command($conn, [string]$sql, [hashtable]$params, [int]$timeout) {
    $cmd = $conn.CreateCommand()
    $cmd.CommandText = $sql
    $cmd.CommandTimeout = $timeout
    foreach ($k in $params.Keys) { [void]$cmd.Parameters.AddWithValue($k, $params[$k]) }
    $cmd
}

function Invoke-Sql($conn, [string]$sql, [hashtable]$params = @{}) {
    $adapter = New-Object System.Data.SqlClient.SqlDataAdapter (New-Command $conn $sql $params 120)
    $table = New-Object System.Data.DataTable
    [void]$adapter.Fill($table)
    , $table
}

function Invoke-NonQuery($conn, [string]$sql, [hashtable]$params = @{}) {
    [void](New-Command $conn $sql $params 3600).ExecuteNonQuery()
}

function Stop-WithMessage([string]$msg) {
    Write-Host ""
    Write-Host $msg -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}


try {
    $windowsLogin = $false
    if (-not $Server) {
        # the program runs its database in a private "user instance";
        # the main SQLEXPRESS instance knows its pipe name while it is alive
        $main = Open-Db ".\SQLEXPRESS" "master" $true
        $rows = Invoke-Sql $main "SELECT owning_principal_name AS owner, instance_pipe_name AS pipe FROM sys.dm_os_child_instances WHERE heart_beat = 'alive'"
        $main.Close()
        if (-not $rows.Rows.Count) {
            Stop-WithMessage "The program's database is not open. Open the ELYASSER program, then run this again."
        }
        $me = "$env:USERDOMAIN\$env:USERNAME"
        $pick = @($rows.Rows | Where-Object { [string]$_.owner -eq $me })
        if (-not $pick.Count) { $pick = @($rows.Rows) }
        $Server = "np:" + [string]$pick[0].pipe
        $windowsLogin = $true
    }

    Write-Host "Connecting to $Server ..."
    $conn = Open-Db $Server "master" $windowsLogin
    $dbs = Invoke-Sql $conn @'
SELECT d.name, CAST(SUM(CAST(mf.size AS bigint)) * 8 / 1024 AS int) AS size_mb
FROM sys.databases d
JOIN sys.master_files mf ON mf.database_id = d.database_id
WHERE d.database_id > 4 AND d.state_desc = 'ONLINE'
GROUP BY d.name
ORDER BY size_mb DESC
'@
    $candidates = @($dbs.Rows)
    if ($Database) { $candidates = @($candidates | Where-Object { [string]$_.name -eq $Database }) }
    if (-not $candidates.Count) { Stop-WithMessage "No shop database found on $Server." }
    $dbName = [string]$candidates[0].name

    # "E:\ELYASSER NEW\ELYASSERDB.MDF" -> "ELYASSERDB"
    $base = (($dbName -split '[\\/]')[-1] -replace '(?i)\.mdf$', '') -replace '[^\w\-]', '_'
    $file = Join-Path $OutDir ("{0}_{1:yyyyMMdd_HHmm}.bak" -f $base, (Get-Date))

    Write-Host "Copying $dbName ($($candidates[0].size_mb) MB) ..."
    Invoke-NonQuery $conn "BACKUP DATABASE @db TO DISK = @file WITH COPY_ONLY, INIT, CHECKSUM, NAME = N'car-bot copy'" @{ "@db" = $dbName; "@file" = $file }
    Write-Host "Checking the copy ..."
    Invoke-NonQuery $conn "RESTORE VERIFYONLY FROM DISK = @file WITH CHECKSUM" @{ "@file" = $file }
    $conn.Close()
} catch {
    Stop-WithMessage ("Failed: " + $_.Exception.Message + "`n`nTake a screenshot of this window and send it.")
}

$sizeMb = (Get-Item -LiteralPath $file).Length / 1MB
Write-Host ""
Write-Host "Done. The copy is checked and complete:" -ForegroundColor Green
Write-Host ("  {0}  ({1:N1} MB)" -f $file, $sizeMb)
Write-Host ""
Write-Host "It holds ALL the shop's data. Keep it private: never upload it or send it in a chat."
Write-Host ""
Read-Host "Press Enter to close"
