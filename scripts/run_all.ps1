# Start the whole LUNA NAV AI stack on real NASA data and open the app. Run via RUN.bat.
#   Person 1  :8001  landing sites from NASA LRO LOLA LDEM_75S_240M
#   Person 2  :8002  Sun/Earth visibility from live NASA/JPL Horizons (offline fallback: NASA NAIF SPICE)
#   Person 3  :3003  rover routes on NASA LRO LOLA LDEM_75S_240M
#   Person 4  :8000  mission planner (LangGraph)
#   Person 5  :5173  Mission Command web app
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy) -or -not (Test-Path -LiteralPath (Join-Path $root 'original_modules\person3\moon_navigation\node_modules'))) {
  throw 'Not set up yet: double-click SETUP.bat first.'
}
foreach ($p in 8000, 8001, 8002, 3003, 5173) {
  if (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) { throw "Port $p is already in use. Run STOP.bat (or close the other program) and try again." }
}

# Backend stack in its own window (closing that window stops the planner; STOP.bat stops everything).
$backend = Start-Process powershell -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', ('"' + (Join-Path $PSScriptRoot 'start_real_nasa.ps1') + '"')) -WorkingDirectory $root -PassThru
# Web app (static files) on port 5173, the planner's allowed CORS origin.
$web = Start-Process $venvPy -ArgumentList @('-m', 'http.server', '5173', '--bind', '127.0.0.1', '--directory', ('"' + (Join-Path $root 'frontend') + '"')) -WindowStyle Minimized -PassThru

Write-Host 'Starting the five services...'
$urls = 'http://127.0.0.1:8000/health', 'http://127.0.0.1:8001/api/v1/health', 'http://127.0.0.1:8002/health', 'http://127.0.0.1:3003/api/v1/health', 'http://127.0.0.1:5173/'
$deadline = (Get-Date).AddSeconds(120)
do {
  Start-Sleep -Seconds 2
  $up = @($urls | Where-Object { try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $_).StatusCode -eq 200 } catch { $false } }).Count
  Write-Host "  $up / 5 ready"
} while ($up -lt 5 -and (Get-Date) -lt $deadline)
if ($up -lt 5) { throw 'Some services did not start within 2 minutes. Look at the backend window for the error.' }

Write-Host "`nLUNA NAV AI is running on NASA data. App: http://localhost:5173" -ForegroundColor Green
Write-Host 'The first mission takes about 45 s (live JPL Horizons). Run STOP.bat when you are done.'
if (-not $NoBrowser) { Start-Process 'http://localhost:5173' }
