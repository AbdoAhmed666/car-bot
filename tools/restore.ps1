<#
Restores the shop database copy (the .bak made by backup.ps1) on the dev laptop.

Needs SQL Server Express installed on the laptop (instance SQLEXPRESS).
Right-click this file -> "Run with PowerShell". It picks the newest
ELYASSERDB_*.bak from Downloads, Desktop, Documents, a USB stick or this
script's folder. To use a specific file:
  powershell -ExecutionPolicy Bypass -File restore.ps1 -BackupFile "D:\ELYASSERDB_20260926_1500.bak"

Creates (or replaces) the database ELyasserDB on the laptop.
Never copy this database back to the shop PC: the laptop's newer SQL Server
upgrades it, and the shop's SQL Server 2008 can't open it any more.
#>
param(
    [string]$BackupFile = "",    # empty = find the newest ELYASSERDB_*.bak (see above)
    [string]$Server = ".\SQLEXPRESS",
    [string]$User = "",          # empty = log in with the Windows account
    [string]$Password = "",
    [string]$Database = "ELyasserDB",
    [string]$StageDir = ""       # where the .bak is copied so the SQL service can read it
)

$ErrorActionPreference = "Stop"


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
    $b["Application Name"] = "car-bot-restore"
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
    $adapter = New-Object System.Data.SqlClient.SqlDataAdapter (New-Command $conn $sql $params 600)
    $table = New-Object System.Data.DataTable
    [void]$adapter.Fill($table)
    , $table
}

function Invoke-NonQuery($conn, [string]$sql, [hashtable]$params = @{}) {
    [void](New-Command $conn $sql $params 3600).ExecuteNonQuery()
}

function Quote-Name([string]$name) { "[" + $name.Replace("]", "]]") + "]" }

function Add-Slash([string]$dir) {
    if ($dir -match '[\\/]$') { return $dir }
    if ($dir.Contains("/")) { return $dir + "/" }
    $dir + "\"
}

function Find-Backup {
    $dirs = @($PSScriptRoot,
              (Join-Path $HOME "Downloads"),
              [System.Environment]::GetFolderPath("Desktop"),
              [System.Environment]::GetFolderPath("MyDocuments"))
    foreach ($d in [System.IO.DriveInfo]::GetDrives()) {
        if ($d.IsReady -and ([string]$d.DriveType -eq "Removable" -or [string]$d.DriveType -eq "Fixed")) {
            $dirs += $d.RootDirectory.FullName
        }
    }
    $all = @(foreach ($dir in $dirs) {
        if (-not $dir) { continue }
        try { Get-ChildItem -LiteralPath $dir -Filter "*.bak" -File -ErrorAction Stop } catch { }
    })
    $ours = @($all | Where-Object { $_.Name -like "ELYASSER*" })
    if ($ours.Count) { $all = $ours }
    $all | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

function Stop-WithMessage([string]$msg) {
    Write-Host ""
    Write-Host $msg -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}


# Windows security features (Smart App Control, WDAC) can run downloaded
# scripts in a restricted mode where .NET calls fail; say so instead of crashing.
if ($ExecutionContext.SessionState.LanguageMode -ne "FullLanguage") {
    Stop-WithMessage ("Windows is running this script in restricted mode (" + $ExecutionContext.SessionState.LanguageMode + ").`n" +
                      "Take a screenshot of this window and send it.")
}

try {
    $BackupFile = $BackupFile.Trim().Trim('"')
    if (-not $BackupFile) {
        $found = Find-Backup
        if (-not $found) {
            Stop-WithMessage ("No backup file (.bak) found in Downloads, Desktop, Documents or on a USB stick.`n" +
                              "Make one first: run backup.ps1 on the shop PC (with the program open), then copy the .bak to this laptop.")
        }
        $BackupFile = $found.FullName
        Write-Host ("Using {0}  ({1:yyyy-MM-dd HH:mm}, {2:N1} MB)" -f $found.FullName, $found.LastWriteTime, ($found.Length / 1MB))
    }
    if (-not (Test-Path -LiteralPath $BackupFile)) { Stop-WithMessage "File not found: $BackupFile" }
    $BackupFile = (Resolve-Path -LiteralPath $BackupFile).ProviderPath
    $onWindows = [System.Environment]::OSVersion.Platform -eq "Win32NT"

    # The SQL Server service runs under its own account and usually can't read
    # the Downloads/Desktop folders, so hand it a copy in a shared folder.
    if (-not $StageDir) {
        if ($onWindows) { $StageDir = Join-Path $env:PUBLIC "car-bot" } else { $StageDir = Split-Path -Parent $BackupFile }
    }
    New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
    $staged = Join-Path $StageDir (Split-Path -Leaf $BackupFile)
    if ($staged -ne $BackupFile) { Copy-Item -LiteralPath $BackupFile -Destination $staged -Force }
    if ($onWindows) { & icacls $staged /grant "*S-1-1-0:(R)" | Out-Null }   # S-1-1-0 = Everyone

    Write-Host "Connecting to $Server ..."
    try {
        $conn = Open-Db $Server "master"
    } catch {
        Stop-WithMessage ("Could not connect to $Server. Is SQL Server Express installed on this laptop?`n`n" + $_.Exception.Message)
    }

    # SQL Server 2008 means this is the shop PC, not the laptop
    $version = [string](Invoke-Sql $conn "SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(64)) AS v").Rows[0].v
    if ($version.StartsWith("10.")) {
        Stop-WithMessage "This PC runs SQL Server 2008 - it looks like the shop PC. Run restore.ps1 on your laptop, not here."
    }

    $files = Invoke-Sql $conn "RESTORE FILELISTONLY FROM DISK = @f" @{ "@f" = $staged }

    $paths = (Invoke-Sql $conn @'
SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260)) AS data_dir,
       CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260)) AS log_dir,
       (SELECT physical_name FROM sys.master_files WHERE database_id = 1 AND file_id = 1) AS master_file
'@).Rows[0]
    $masterFile = [string]$paths.master_file
    $fallback = $masterFile.Substring(0, $masterFile.LastIndexOfAny([char[]]@('\', '/')) + 1)
    $dataDir = [string]$paths.data_dir
    $logDir = [string]$paths.log_dir
    if (-not $dataDir) { $dataDir = $fallback }
    if (-not $logDir) { $logDir = $dataDir }
    $dataDir = Add-Slash $dataDir
    $logDir = Add-Slash $logDir

    # put every file of the backup in this server's folders, named after $Database
    $moves = @()
    $params = @{ "@db" = $Database; "@f" = $staged }
    $i = 0; $nData = 0; $nLog = 0
    foreach ($r in $files.Rows) {
        if ([string]$r.Type -eq "L") {
            if ($nLog -eq 0) { $target = "$logDir${Database}_log.ldf" } else { $target = "$logDir${Database}_log$nLog.ldf" }
            $nLog++
        } else {
            if ($nData -eq 0) { $target = "$dataDir$Database.mdf" } else { $target = "$dataDir${Database}_$nData.ndf" }
            $nData++
        }
        $moves += "MOVE @l$i TO @p$i"
        $params["@l$i"] = [string]$r.LogicalName
        $params["@p$i"] = $target
        $i++
    }

    $exists = [int](Invoke-Sql $conn "SELECT COUNT(*) AS n FROM sys.databases WHERE name = @db" @{ "@db" = $Database }).Rows[0].n
    if ($exists) {
        Write-Host "Replacing the existing $Database ..."
        Invoke-NonQuery $conn "ALTER DATABASE $(Quote-Name $Database) SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
    }
    Write-Host "Restoring $Database (the first time on a newer SQL Server it also upgrades it - give it a minute) ..."
    try {
        Invoke-NonQuery $conn ("RESTORE DATABASE @db FROM DISK = @f WITH REPLACE, RECOVERY, " + ($moves -join ", ")) $params
    } finally {
        try { Invoke-NonQuery $conn "ALTER DATABASE $(Quote-Name $Database) SET MULTI_USER" } catch { }
    }
    # the owner recorded in the backup is a Windows account from the shop PC
    try { Invoke-NonQuery $conn "ALTER AUTHORIZATION ON DATABASE::$(Quote-Name $Database) TO [sa]" } catch { }
    $conn.Close()

    # quick look so you can tell it is the right data
    $db = Open-Db $Server $Database
    $tables = [int](Invoke-Sql $db "SELECT COUNT(*) AS n FROM sys.tables").Rows[0].n
    $summary = "  tables: $tables"
    try {
        $s = (Invoke-Sql $db "SELECT COUNT(*) AS n, MAX(pdate) AS last_sale FROM dbo.Sal_Invoice").Rows[0]
        $summary += ("`n  sales invoices: {0:N0}, latest: {1:yyyy-MM-dd HH:mm}" -f [int]$s.n, $s.last_sale)
    } catch { }
    try {
        $n = [int](Invoke-Sql $db "SELECT COUNT(*) AS n FROM dbo.Item").Rows[0].n
        $summary += ("`n  items: {0:N0}" -f $n)
    } catch { }
    $db.Close()
} catch {
    Stop-WithMessage ("Failed: " + $_.Exception.Message + "`n`nTake a screenshot of this window and send it.")
}

Write-Host ""
Write-Host "Done. $Database is on $Server" -ForegroundColor Green
Write-Host $summary
Write-Host ""
Read-Host "Press Enter to close"
