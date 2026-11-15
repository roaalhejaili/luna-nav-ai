# One-time setup for LUNA NAV AI (Windows). Run via SETUP.bat.
# Creates .venv, installs Python packages for Persons 1, 2 and 4, installs Person 3's Node packages,
# and checks the bundled NASA data files against DATA_CHECKSUMS.txt.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }

Step 'Checking Python 3.11+'
$py = $null
foreach ($cand in @(@('py', '-3.12'), @('py', '-3.11'), @('py', '-3.13'), @('py', '-3'), @('python'))) {
  try {
    $exe = $cand[0]; $args0 = @($cand | Select-Object -Skip 1)
    $v = & $exe @args0 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $v -and [version]$v -ge [version]'3.11') { $py = $cand; Write-Host "Using Python $v ($($cand -join ' '))"; break }
  } catch {}
}
if (-not $py) { throw 'Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ (tick "Add to PATH"), then run SETUP.bat again.' }

Step 'Checking Node.js 18+'
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw 'Node.js 18+ is required for the navigation module. Install the LTS from https://nodejs.org/, then run SETUP.bat again.' }
$nv = (& node --version).TrimStart('v')
if ([version]$nv -lt [version]'18.0') { throw "Node.js $nv is too old; install Node 18 or newer." }
Write-Host "Using Node $nv"

Step 'Checking bundled NASA data (SHA-256)'
$bad = 0
foreach ($line in Get-Content -LiteralPath (Join-Path $root 'DATA_CHECKSUMS.txt')) {
  if (-not $line.Trim() -or $line.StartsWith('#')) { continue }
  $hash, $rel = $line -split '\s+', 2
  $file = Join-Path $root $rel
  if (-not (Test-Path -LiteralPath $file)) { Write-Host "MISSING $rel" -ForegroundColor Red; $bad++; continue }
  $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
  if ($actual -ne $hash.ToUpper()) { Write-Host "CORRUPT $rel" -ForegroundColor Red; $bad++ } else { Write-Host "ok  $rel" }
}
if ($bad) { throw "$bad NASA data file(s) missing or corrupt. Re-extract the zip (or run scripts\get_nasa_lola.py and original_modules\person2\member2\scripts\fetch_kernels.py)." }

Step 'Creating Python environment (.venv)'
$venvPy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
  $exe = $py[0]; $args0 = @($py | Select-Object -Skip 1)
  & $exe @args0 -m venv (Join-Path $root '.venv'); if ($LASTEXITCODE) { throw 'Could not create .venv' }
}
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install --quiet -r requirements.txt -r original_modules\person1\requirements.txt -r original_modules\person2\member2\requirements.txt
if ($LASTEXITCODE) { throw 'pip install failed (check your internet connection and run SETUP.bat again).' }

Step 'Installing navigation module packages (npm)'
Push-Location -LiteralPath (Join-Path $root 'original_modules\person3\moon_navigation')
try {
  & npm.cmd ci --no-audit --no-fund
  if ($LASTEXITCODE) { & npm.cmd install --no-audit --no-fund; if ($LASTEXITCODE) { throw 'npm install failed' } }
} finally { Pop-Location }

Write-Host "`nSetup complete. Double-click RUN.bat to start LUNA NAV AI." -ForegroundColor Green
