# Stop every LUNA NAV AI service (ports 8000, 8001, 8002, 3003, 5173). Run via STOP.bat.
foreach ($p in 8000, 8001, 8002, 3003, 5173) {
  $owners = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($id in $owners) {
    try { Stop-Process -Id $id -Force -ErrorAction Stop; Write-Host "Stopped port $p (process $id)" } catch {}
  }
}
Write-Host 'All LUNA NAV AI services stopped.'
