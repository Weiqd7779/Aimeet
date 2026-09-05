# Start Next.js dev with nothing stale on :3000 (a leftover node once pushed us to :3001,
# which CORS did not allow). Kills the tree on exit as well.
param([int]$Port = 3000)

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
    Start-Sleep -Milliseconds 500
}

Clear-Stale

$proc = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev", "--", "--port", "$Port") `
    -WorkingDirectory $here -NoNewWindow -PassThru
try {
    Wait-Process -Id $proc.Id
} finally {
    Stop-Tree $proc.Id "shutdown"
    Clear-Stale
}
