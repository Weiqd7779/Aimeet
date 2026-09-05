# Start the API for development with a guarantee that nothing stale survives.
#
# Why: on Windows, stopping only the uvicorn reloader leaves its spawned worker alive and
# still bound to :8000. A "restarted" server binds too, but connections keep going to the
# orphan, which runs whatever code it loaded last. We debugged a prompt leak for an hour
# that was really a 20:39 worker serving a 20:58 repo.
#
# Three layers:
#   1. before start: kill every process tree holding :8000
#   2. before start: kill every python/uvicorn process whose command line points at this
#      api directory (workers that lost the port but are still running)
#   3. on exit (Ctrl+C or crash): kill the whole tree we started, so we never leave one
param([int]$Port = 8000)

$here = $PSScriptRoot

function Stop-Tree([int]$id, [string]$why) {
    if ($id -le 0 -or $id -eq $PID) { return }
    Write-Host "[dev.ps1] killing pid $id and children ($why)"
    taskkill /PID $id /T /F 2>$null | Out-Null
}

function Clear-Stale {
    $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) { Stop-Tree $id "holds port $Port" }

    $mine = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -and
        ($_.CommandLine -like "*uvicorn*app.main:app*" -or $_.CommandLine -like "*multiprocessing*") -and
        ($_.CommandLine -like "*$here*" -or $_.ExecutablePath -like "$here*")
    }
    foreach ($p in $mine) { Stop-Tree $p.ProcessId "stale api process" }

    Start-Sleep -Milliseconds 500
    $left = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($left) {
        Write-Host "[dev.ps1] WARNING: port $Port still held by $($left.OwningProcess -join ', ')"
    }
}

Clear-Stale

$proc = Start-Process -FilePath "uv" -ArgumentList @("run", "uvicorn", "app.main:app", "--reload", "--reload-dir", "app", "--port", "$Port") `
    -WorkingDirectory $here -NoNewWindow -PassThru
try {
    Wait-Process -Id $proc.Id
} finally {
    Stop-Tree $proc.Id "shutdown"
    Clear-Stale
}
