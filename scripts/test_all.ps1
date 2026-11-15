# Run every test suite. Run via TEST.bat.
# Unit suites always run. If RUN.bat is running (port 8000 answers), the live NASA API suite runs too.
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw 'Not set up yet: double-click SETUP.bat first.' }
$results = [ordered]@{}
function Suite($name, $dir, [scriptblock]$cmd) {
  Write-Host "`n== $name" -ForegroundColor Cyan
  Push-Location -LiteralPath $dir
  try { & $cmd; $results[$name] = if ($LASTEXITCODE -eq 0) { 'PASS' } else { "FAIL (exit $LASTEXITCODE)" } } finally { Pop-Location }
}
Suite 'Person 4 planner'      $root                                                       { & $py -m pytest tests -q --disable-warnings -p no:cacheprovider }
Suite 'Person 1 sites'        (Join-Path $root 'original_modules\person1')                { & $py -m pytest tests -q --disable-warnings -p no:cacheprovider }
Suite 'Person 2 visibility'   (Join-Path $root 'original_modules\person2\member2')        { & $py -m pytest -q --disable-warnings -p no:cacheprovider }
Suite 'Person 3 navigation'   (Join-Path $root 'original_modules\person3\moon_navigation') { & npx.cmd vitest run }
$live = try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:8000/health').StatusCode -eq 200 } catch { $false }
if ($live) {
  Suite 'Live NASA API (25 tests)' $root {
    & $py -I (Join-Path $root 'tests_live\live_api_test.py') (Join-Path $root 'original_modules\person2\member2\data\lola\ldem_75s_240m.img') (Join-Path $root 'tests_live\live_api_results.json')
  }
} else { $results['Live NASA API (25 tests)'] = 'SKIPPED (start RUN.bat first, then run TEST.bat again)' }
Write-Host "`n== Summary" -ForegroundColor Cyan
$results.GetEnumerator() | ForEach-Object { Write-Host ("{0,-28} {1}" -f $_.Key, $_.Value) }
Write-Host '(Windows only: if Person 4 crashes with an access violation, run TEST.bat again; it is a known TestClient issue, not a code failure.)'
