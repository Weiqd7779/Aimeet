# One-shot (re)start of the whole POC: API on :8000 + web on :3000, each in its own window.
#
#   .\dev.ps1          start (or restart) both; stale processes on the ports are killed first
#   .\dev.ps1 -Stop    stop everything and free both ports
#
# Each window runs the existing api/dev.ps1 / web/dev.ps1, which own the "kill stale tree
# before start, kill our tree on exit" logic. Closing a window (or Ctrl+C in it) stops that
# service cleanly. Rerunning this script is the fast "restart" path.
param([switch]$Stop)

$here = $PSScriptRoot
$ports = @{ api = 8000; web = 3000 }

function Stop-Port([int]$port) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) {
        if ($id -gt 0 -and $id -ne $PID) {
            Write-Host "[dev] killing pid $id (port $port)"
            taskkill /PID $id /T /F 2>$null | Out-Null
        }
    }
}

function Stop-Orphans {
    # uvicorn workers that lost the port but still run the api code (Windows reloader quirk)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -and
        $_.CommandLine -like "*$here\api*" -and
        ($_.CommandLine -like "*uvicorn*" -or $_.CommandLine -like "*multiprocessing*")
    } | ForEach-Object {
        Write-Host "[dev] killing orphan api pid $($_.ProcessId)"
        taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null
    }
}

foreach ($port in $ports.Values) { Stop-Port $port }
Stop-Orphans
Start-Sleep -Milliseconds 700

if ($Stop) {
    Write-Host "[dev] stopped."
    exit 0
}

foreach ($name in "api", "web") {
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-ExecutionPolicy", "Bypass",
        "-Command", "`$host.UI.RawUI.WindowTitle = 'aimeet $name'; & '$here\$name\dev.ps1'"
    ) -WorkingDirectory "$here\$name"
}

Write-Host "[dev] starting api -> http://localhost:$($ports.api)  web -> http://localhost:$($ports.web)"
$deadline = (Get-Date).AddSeconds(40)
do {
    Start-Sleep -Seconds 1
    $up = @{}
    foreach ($name in $ports.Keys) {
        $up[$name] = [bool](Get-NetTCPConnection -LocalPort $ports[$name] -State Listen -ErrorAction SilentlyContinue)
    }
} until (($up.Values -notcontains $false) -or (Get-Date) -gt $deadline)

foreach ($name in $ports.Keys) {
    Write-Host ("[dev] {0,-3} :{1}  {2}" -f $name, $ports[$name], $(if ($up[$name]) { "UP" } else { "NOT UP (check its window)" }))
}
