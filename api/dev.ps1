# Start the API for development, making sure nothing stale is still holding port 8000.
#
# Why: on Windows, killing only the uvicorn reloader leaves its worker alive and still
# bound to the port. A "restarted" server then binds too, but connections keep going to the
# orphan - which runs whatever code it loaded last. We debugged a prompt leak for an hour
# that was really a 20:39 worker serving a 20:58 repo.
$ErrorActionPreference = "SilentlyContinue"
$owners = Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pid_ in $owners) {
    Write-Host "port 8000 held by pid $pid_ - killing its whole tree"
    taskkill /PID $pid_ /T /F | Out-Null
}
$ErrorActionPreference = "Stop"
uv run uvicorn app.main:app --reload --reload-dir app
