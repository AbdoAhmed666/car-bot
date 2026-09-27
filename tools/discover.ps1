<#
Read-only look at the shop program's database.

Run on the shop PC, with the shop program OPEN:
  right-click this file -> "Run with PowerShell"

It finds every SQL Server on this PC (including the private "user instances"
some programs start on their own), lists databases, tables, columns and row
counts, then searches the disks for database files and connection settings.

Writes two files next to this script:
  structure.txt   what it found. No business data.
  samples.txt     first rows of the biggest tables. Real data - your call whether to share it.

It only reads. Nothing in any database or file is changed.
Needs nothing installed: uses the SQL client that ships with Windows.
#>
param(
    [string]$Server = "",           # empty = every SQL Server instance on this PC
    [string]$User = "",             # empty = log in with the Windows account
    [string]$Password = "",
    [string[]]$SearchRoots = @(),   # empty = all local disks
    [int]$SampleTables = 25,
    [int]$SampleRows = 3
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$structPath = Join-Path $here "structure.txt"
$samplePath = Join-Path $here "samples.txt"
$struct = New-Object System.Collections.Generic.List[string]
$samples = New-Object System.Collections.Generic.List[string]
$connected = 0
$dbCount = 0

# column types that are pointless (or huge) to print
$skipTypes = @("image", "varbinary", "binary", "timestamp", "geography", "geometry", "hierarchyid", "xml", "sql_variant")
# SQL Server's own files, not the shop's
$systemDbFiles = @("master", "mastlog", "model", "modellog", "msdbdata", "msdblog", "tempdb", "templog",
                   "mssqlsystemresource", "distmdl")


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
    $b["Connect Timeout"] = 10
    $b["Application Name"] = "car-bot-discover"
    $conn = New-Object System.Data.SqlClient.SqlConnection $b.ConnectionString
    $conn.Open()
    $conn
}

function Invoke-Sql($conn, [string]$sql) {
    $cmd = $conn.CreateCommand()
    $cmd.CommandText = $sql
    $cmd.CommandTimeout = 120
    $adapter = New-Object System.Data.SqlClient.SqlDataAdapter $cmd
    $table = New-Object System.Data.DataTable
    [void]$adapter.Fill($table)
    , $table
}

function Format-Value($v) {
    if ($null -eq $v -or $v -is [System.DBNull]) { return "NULL" }
    if ($v -is [datetime]) { return $v.ToString("yyyy-MM-dd HH:mm") }
    if ($v -is [decimal] -or $v -is [double] -or $v -is [single]) {
        return $v.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    }
    $s = ([string]$v) -replace "\s+", " "
    if ($s.Length -gt 60) { $s = $s.Substring(0, 60) + "..." }
    $s
}

function Quote-Name([string]$name) { "[" + $name.Replace("]", "]]") + "]" }

function Add-Header([string]$title) {
    $struct.Add("")
    $struct.Add("== $title ==")
}


function Describe-Db($conn, [string]$label) {
    $tables = Invoke-Sql $conn @'
SELECT s.name AS sch, o.name AS obj, o.object_id AS oid, o.type AS kind,
       SUM(CASE WHEN p.index_id IN (0, 1) THEN p.rows ELSE 0 END) AS row_count
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
LEFT JOIN sys.partitions p ON p.object_id = o.object_id
WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0
GROUP BY s.name, o.name, o.object_id, o.type
ORDER BY row_count DESC, s.name, o.name
'@

    $colRows = Invoke-Sql $conn @'
SELECT c.object_id AS oid, c.name AS col, ty.name AS typ
FROM sys.columns c
JOIN sys.objects o ON o.object_id = c.object_id
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0
ORDER BY c.object_id, c.column_id
'@

    $cols = @{}
    foreach ($r in $colRows.Rows) {
        $oid = [int]$r.oid
        if (-not $cols.ContainsKey($oid)) { $cols[$oid] = New-Object System.Collections.Generic.List[object] }
        $cols[$oid].Add([pscustomobject]@{ Name = [string]$r.col; Type = [string]$r.typ })
    }

    $all = @($tables.Rows)
    $full = @($all | Where-Object { $_.kind.Trim() -eq "U" -and [int64]$_.row_count -gt 0 })
    $empty = @($all | Where-Object { $_.kind.Trim() -eq "U" -and [int64]$_.row_count -eq 0 })
    $views = @($all | Where-Object { $_.kind.Trim() -eq "V" })

    $struct.Add("-- $($full.Count) tables with data, $($empty.Count) empty tables, $($views.Count) views")

    foreach ($t in $full) {
        $struct.Add("")
        $struct.Add(("{0}.{1}  ({2:N0} rows)" -f $t.sch, $t.obj, [int64]$t.row_count))
        $list = $cols[[int]$t.oid]
        if ($list) { $struct.Add("    " + (($list | ForEach-Object { "$($_.Name) $($_.Type)" }) -join ", ")) }
    }

    if ($views.Count) {
        $struct.Add("")
        $struct.Add("-- views")
        foreach ($v in $views) {
            $list = $cols[[int]$v.oid]
            $colText = ""
            if ($list) { $colText = ($list | ForEach-Object { $_.Name }) -join ", " }
            $struct.Add(("{0}.{1}: {2}" -f $v.sch, $v.obj, $colText))
        }
    }

    if ($empty.Count) {
        $struct.Add("")
        $struct.Add("-- empty tables: " + (($empty | ForEach-Object { "$($_.sch).$($_.obj)" }) -join ", "))
    }

    try {
        $fks = Invoke-Sql $conn @'
SELECT OBJECT_SCHEMA_NAME(fk.parent_object_id) + '.' + OBJECT_NAME(fk.parent_object_id) + '.' + cp.name AS child,
       OBJECT_SCHEMA_NAME(fk.referenced_object_id) + '.' + OBJECT_NAME(fk.referenced_object_id) + '.' + cr.name AS parent
FROM sys.foreign_key_columns fk
JOIN sys.columns cp ON cp.object_id = fk.parent_object_id AND cp.column_id = fk.parent_column_id
JOIN sys.columns cr ON cr.object_id = fk.referenced_object_id AND cr.column_id = fk.referenced_column_id
ORDER BY 1
'@
        if ($fks.Rows.Count) {
            $struct.Add("")
            $struct.Add("-- relations")
            foreach ($r in $fks.Rows) { $struct.Add("  $($r.child) -> $($r.parent)") }
        }
    } catch { $struct.Add("  (relations skipped: $($_.Exception.Message))") }

    try {
        $procs = Invoke-Sql $conn "SELECT name FROM sys.procedures WHERE is_ms_shipped = 0 ORDER BY name"
        if ($procs.Rows.Count) {
            $struct.Add("")
            $struct.Add("-- stored procedures: " + (($procs.Rows | ForEach-Object { $_.name }) -join ", "))
        }
    } catch { }

    # a few real rows from the biggest tables, so the column meanings are obvious
    $samples.Add("")
    $samples.Add("#################### $label ####################")
    foreach ($t in ($full | Select-Object -First $SampleTables)) {
        $use = @($cols[[int]$t.oid] | Where-Object { $skipTypes -notcontains $_.Type })
        if (-not $use.Count) { continue }
        $colSql = ($use | ForEach-Object { Quote-Name $_.Name }) -join ", "
        $sql = "SELECT TOP ($SampleRows) $colSql FROM $(Quote-Name $t.sch).$(Quote-Name $t.obj) WITH (NOLOCK)"
        $samples.Add("")
        $samples.Add(("{0}.{1}  ({2:N0} rows)" -f $t.sch, $t.obj, [int64]$t.row_count))
        try {
            $data = Invoke-Sql $conn $sql
            foreach ($row in $data.Rows) {
                $parts = foreach ($c in $use) { "$($c.Name)=" + (Format-Value $row[$c.Name]) }
                $samples.Add("  " + ($parts -join " | "))
            }
        } catch { $samples.Add("  (skipped: $($_.Exception.Message))") }
    }
}


function Describe-Server([string]$srv, [bool]$windowsLogin = $false) {
    $struct.Add("")
    $struct.Add("******************** SERVER: $srv ********************")
    Write-Host "Connecting to $srv ..."
    try {
        $master = Open-Db $srv "master" $windowsLogin
    } catch {
        $struct.Add("  (could not connect: $($_.Exception.Message))")
        Write-Host "  could not connect: $($_.Exception.Message)" -ForegroundColor Yellow
        return
    }
    $script:connected++

    Add-Header "SQL Server"
    try {
        $r = (Invoke-Sql $master @'
SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(64)) AS ver,
       CAST(SERVERPROPERTY('Edition') AS nvarchar(128)) AS edition,
       CAST(SERVERPROPERTY('Collation') AS nvarchar(128)) AS coll,
       @@VERSION AS full_ver,
       SUSER_SNAME() AS login_name,
       IS_SRVROLEMEMBER('sysadmin') AS is_admin
'@).Rows[0]
        $struct.Add("  " + (([string]$r.full_ver) -split "`n")[0].Trim())
        $struct.Add("  version $($r.ver) | $($r.edition) | collation $($r.coll)")
        $struct.Add("  logged in as $($r.login_name) | sysadmin: $($r.is_admin)")
    } catch { $struct.Add("  (skipped: $($_.Exception.Message))") }

    Add-Header "Programs connected right now"
    try {
        $rows = Invoke-Sql $master @'
SELECT program_name, login_name, COUNT(*) AS sessions
FROM sys.dm_exec_sessions
WHERE is_user_process = 1 AND session_id <> @@SPID
GROUP BY program_name, login_name
ORDER BY sessions DESC
'@
        if (-not $rows.Rows.Count) { $struct.Add("  (none - is the shop program open?)") }
        foreach ($r in $rows.Rows) { $struct.Add("  $($r.program_name) | login: $($r.login_name) | sessions: $($r.sessions)") }
    } catch { $struct.Add("  (skipped: $($_.Exception.Message))") }

    # programs using "User Instance=True" get a private SQL Server of their own;
    # their databases never show up on the main instance
    $children = @()
    Add-Header "User instances"
    try {
        $rows = Invoke-Sql $master "SELECT owning_principal_name AS owner, instance_pipe_name AS pipe, heart_beat AS hb FROM sys.dm_os_child_instances"
        if (-not $rows.Rows.Count) { $struct.Add("  (none running)") }
        foreach ($r in $rows.Rows) {
            $struct.Add("  $($r.owner) | $($r.hb) | $($r.pipe)")
            if (([string]$r.hb).Trim() -eq "alive") { $children += [string]$r.pipe }
        }
    } catch { $struct.Add("  (skipped: $($_.Exception.Message))") }

    $dbs = $null
    Add-Header "Databases"
    try {
        $dbs = Invoke-Sql $master @'
SELECT d.name, d.create_date, d.state_desc AS state, d.recovery_model_desc AS recovery,
       CAST(SUM(CAST(mf.size AS bigint)) * 8 / 1024 AS int) AS size_mb,
       MIN(CASE WHEN mf.type = 0 THEN mf.physical_name END) AS data_file
FROM sys.databases d
LEFT JOIN sys.master_files mf ON mf.database_id = d.database_id
WHERE d.database_id > 4
GROUP BY d.name, d.create_date, d.state_desc, d.recovery_model_desc
ORDER BY size_mb DESC
'@
        if (-not $dbs.Rows.Count) { $struct.Add("  (no shop databases on this server)") }
        foreach ($d in $dbs.Rows) {
            $struct.Add(("  {0} | {1} MB | created {2:yyyy-MM-dd} | {3} | recovery {4} | {5}" -f
                $d.name, $d.size_mb, $d.create_date, $d.state, $d.recovery, $d.data_file))
        }
    } catch { $struct.Add("  (skipped: $($_.Exception.Message))") }

    Add-Header "Recent backups"
    try {
        $rows = Invoke-Sql $master @'
SELECT TOP 15 bs.database_name, bs.backup_finish_date, bs.type, bmf.physical_device_name
FROM msdb.dbo.backupset bs
JOIN msdb.dbo.backupmediafamily bmf ON bmf.media_set_id = bs.media_set_id
ORDER BY bs.backup_finish_date DESC
'@
        if (-not $rows.Rows.Count) { $struct.Add("  (no backups recorded)") }
        foreach ($r in $rows.Rows) {
            $struct.Add(("  {0:yyyy-MM-dd HH:mm} | {1} | type {2} | {3}" -f $r.backup_finish_date, $r.database_name, $r.type, $r.physical_device_name))
        }
    } catch { $struct.Add("  (skipped: $($_.Exception.Message))") }

    if ($dbs) {
        foreach ($d in $dbs.Rows) {
            $name = [string]$d.name
            if ($d.state -ne "ONLINE") { continue }
            Write-Host "  reading $name ..."
            $struct.Add("")
            $struct.Add("#################### DB: $name ####################")
            try {
                $conn = Open-Db $srv $name $windowsLogin
            } catch {
                $struct.Add("  (no access: $($_.Exception.Message))")
                continue
            }
            try {
                Describe-Db $conn "$srv / $name"
                $script:dbCount++
            } catch {
                $struct.Add("  (error: $($_.Exception.Message))")
            } finally {
                $conn.Close()
            }
        }
    }
    $master.Close()

    # user instances only accept the Windows login of their owner
    foreach ($pipe in $children) { Describe-Server ("np:" + $pipe) $true }
}


function Get-LocalInstances {
    $names = New-Object System.Collections.Generic.List[string]
    foreach ($key in @("HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL",
                       "HKLM:\SOFTWARE\Wow6432Node\Microsoft\Microsoft SQL Server\Instance Names\SQL")) {
        try {
            $props = Get-ItemProperty -Path $key -ErrorAction Stop
            foreach ($p in $props.PSObject.Properties) {
                if ($p.Name -notlike "PS*" -and -not $names.Contains($p.Name)) { $names.Add($p.Name) }
            }
        } catch { }
    }
    , $names
}

function Find-DbFiles([string[]]$roots) {
    $exts = @(".mdf", ".ndf", ".ldf", ".mdb", ".accdb")
    $skipDirs = @("windows", '$recycle.bin', "system volume information", "windowsapps", "winsxs")
    $found = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    $stack = New-Object "System.Collections.Generic.Stack[string]"
    foreach ($r in $roots) { $stack.Push($r) }
    while ($stack.Count -gt 0) {
        $dir = $stack.Pop()
        try {
            foreach ($f in [System.IO.Directory]::EnumerateFiles($dir)) {
                if ($exts -contains [System.IO.Path]::GetExtension($f).ToLowerInvariant()) {
                    $found.Add((New-Object System.IO.FileInfo $f))
                }
            }
            foreach ($d in [System.IO.Directory]::EnumerateDirectories($dir)) {
                if ($skipDirs -contains [System.IO.Path]::GetFileName($d).ToLowerInvariant()) { continue }
                # junctions like "Application Data" loop back on themselves
                if (([System.IO.File]::GetAttributes($d) -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
                $stack.Push($d)
            }
        } catch { }   # access denied, path too long: skip that folder
    }
    , $found
}

function Find-ConnectionSettings($dbFiles) {
    $dirs = New-Object "System.Collections.Generic.HashSet[string]" ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($f in $dbFiles) {
        [void]$dirs.Add($f.DirectoryName)
        if ($f.Directory.Parent) { [void]$dirs.Add($f.Directory.Parent.FullName) }
    }
    foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $pf) { continue }
        try { foreach ($d in [System.IO.Directory]::GetDirectories($pf)) { [void]$dirs.Add($d) } } catch { }
    }

    $exts = @(".config", ".ini", ".udl", ".xml", ".json", ".txt")
    $pattern = '(?i)(AttachDbFilename|Initial Catalog|Data Source\s*=|User Instance|Database\s*=|Provider\s*=\s*(SQLOLEDB|SQLNCLI|Microsoft\.(Jet|ACE)))'
    $hits = New-Object System.Collections.Generic.List[string]
    foreach ($dir in $dirs) {
        try { $files = [System.IO.Directory]::GetFiles($dir) } catch { continue }
        foreach ($file in $files) {
            if ($exts -notcontains [System.IO.Path]::GetExtension($file).ToLowerInvariant()) { continue }
            try {
                if ((New-Object System.IO.FileInfo $file).Length -gt 256KB) { continue }
                $lines = @([System.IO.File]::ReadAllLines($file) | Where-Object { $_ -match $pattern } | Select-Object -First 5)
                if (-not $lines.Count) { continue }
                $hits.Add("  $file")
                foreach ($line in $lines) {
                    $clean = $line.Trim() -replace '(?i)((?:password|pwd)\s*=\s*)[^;"''<>]*', '$1***'
                    if ($clean.Length -gt 220) { $clean = $clean.Substring(0, 220) + "..." }
                    $hits.Add("      $clean")
                }
            } catch { }
        }
    }
    , $hits
}


$struct.Add("car-bot discovery  " + (Get-Date -Format "yyyy-MM-dd HH:mm"))
$struct.Add("Computer: $env:COMPUTERNAME | user: $env:USERNAME")
$samples.Add("car-bot samples  " + (Get-Date -Format "yyyy-MM-dd HH:mm"))
$samples.Add("First $SampleRows rows of the $SampleTables biggest tables in each database.")

# 1. SQL Server instances
$servers = @()
if ($Server) {
    $servers = @($Server)
} else {
    Add-Header "SQL Server instances on this PC"
    $instances = Get-LocalInstances
    if (-not $instances.Count) { $struct.Add("  (none found in the registry)") }
    foreach ($n in $instances) {
        if ($n -eq "MSSQLSERVER") { $svc = "MSSQLSERVER"; $srv = "." } else { $svc = 'MSSQL$' + $n; $srv = ".\$n" }
        $status = "unknown"
        try { $status = [string](Get-Service -Name $svc -ErrorAction Stop).Status } catch { }
        $struct.Add("  $n ($status)")
        if ($status -eq "Running") { $servers += $srv }
    }
    if (-not $servers.Count) { $servers = @(".\SQLEXPRESS") }
}
foreach ($srv in $servers) { Describe-Server $srv }

# 2. database files anywhere on the disks (a program can keep its data in a
#    file it attaches only while running)
if (-not $SearchRoots.Count) {
    $SearchRoots = @([System.IO.DriveInfo]::GetDrives() |
        Where-Object { $_.DriveType -eq "Fixed" -and $_.IsReady } |
        ForEach-Object { $_.RootDirectory.FullName })
}
Write-Host "Searching $($SearchRoots -join ', ') for database files (can take a minute) ..."
$allFiles = Find-DbFiles $SearchRoots
$dbFiles = @($allFiles |
    Where-Object { $systemDbFiles -notcontains [System.IO.Path]::GetFileNameWithoutExtension($_.Name).ToLowerInvariant() } |
    Sort-Object LastWriteTime -Descending)

Add-Header "Database files on disk (newest first)"
if (-not $dbFiles.Count) { $struct.Add("  (none found)") }
foreach ($f in ($dbFiles | Select-Object -First 60)) {
    $struct.Add(("  {0:yyyy-MM-dd HH:mm} | {1,10:N1} MB | {2}" -f $f.LastWriteTime, ($f.Length / 1MB), $f.FullName))
}

# 3. how programs are told where their database is
Write-Host "Looking for connection settings ..."
$settings = Find-ConnectionSettings $dbFiles
Add-Header "Connection settings in program files (passwords hidden)"
if (-not $settings.Count) { $struct.Add("  (none found)") }
foreach ($line in $settings) { $struct.Add($line) }

$utf8 = New-Object System.Text.UTF8Encoding $true
[System.IO.File]::WriteAllLines($structPath, $struct, $utf8)
[System.IO.File]::WriteAllLines($samplePath, $samples, $utf8)

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  SQL servers reached: $connected | databases read: $dbCount | database files on disk: $($dbFiles.Count)"
Write-Host "  $structPath"
Write-Host "  $samplePath"
Write-Host ""
Read-Host "Press Enter to close"
