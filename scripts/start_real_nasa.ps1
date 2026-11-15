# Start the whole team stack on NASA data for an accuracy test.
#   Person 1: NASA LOLA LDEM_75S_240M (polar, 240 m), candidates on local high ground near the pole,
#             region 90 S to 87.5 S. Use -Person1Dem cylindrical for the original LDEM_16 grid pattern.
#   Person 2: live NASA/JPL Horizons + horizon computed from NASA LOLA LDEM_75S_240M
#   Person 3: A*/Dijkstra routes on the same LOLA LDEM_75S_240M (240 m)
#   Person 4: accepts supplier REAL data (shown as UNVERIFIED) with a warning, for testing only
# Prerequisites (once):
#   .venv\Scripts\python.exe -m pip install spiceypy truststore
#   .venv\Scripts\python.exe scripts\get_nasa_lola.py
#   (optional) .venv\Scripts\python.exe scripts\get_nasa_lola.py --product ldem_16
# Optional Gemini (language only, never measurements):
#   $env:GEMINI_API_KEY = '<key from Google AI Studio>'   then run this script
#   -GeminiModel <name> to change the model, -GeminiLang ar for an Arabic summary
param([int]$Port = 8000, [ValidateSet('polar', 'cylindrical')][string]$Person1Dem = 'polar',
      [double]$NavTargetLat = -90, [double]$NavTargetLon = 0,
      [string]$GeminiModel = '', [ValidateSet('en', 'ar')][string]$GeminiLang = 'en')
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$lola = Join-Path $root 'original_modules\person2\member2\data\lola\ldem_75s_240m.img'
if (-not (Test-Path -LiteralPath $lola)) { throw 'Missing LDEM_75S_240M. Run: .venv\Scripts\python.exe scripts\get_nasa_lola.py' }
if ($Person1Dem -eq 'polar') {
  $dem = $lola
  $env:LUNA_P1_CANDIDATE_STRATEGY = 'elevated'
} else {
  $dem = Join-Path $root 'original_modules\person1\data\ldem_16.img'
  if (-not (Test-Path -LiteralPath $dem)) { throw 'Missing LDEM_16. Run: .venv\Scripts\python.exe scripts\get_nasa_lola.py --product ldem_16' }
  $env:LUNA_P1_CANDIDATE_STRATEGY = 'grid'
}
$env:LUNA_DEM_PATH = $dem
$env:LUNA_DEM_LABEL_PATH = [IO.Path]::ChangeExtension($dem, '.lbl')
$env:LUNA_MEMBER1_DATA_MODE = 'real'
$env:LUNA_REGION_MIN_LAT = '-90'; $env:LUNA_REGION_MAX_LAT = '-87.5'
$env:LUNA_REGION_MIN_LON = '-180'; $env:LUNA_REGION_MAX_LON = '180'
$env:LUNA_CANDIDATE_COUNT = '6'
$env:LUNA_MEMBER2_HORIZON = 'lola'
$env:LUNA_HTTP_TIMEOUT_SECONDS = '60'
$env:LUNA_VISIBILITY_TIMEOUT_SECONDS = '300'
$env:LUNA_ALLOW_UNVERIFIED_RECOMMENDATION = '1'
# Person 3 routes on the same NASA LOLA LDEM_75S_240M (+/-80 km, native 240 m) instead of its synthetic fixture.
$env:LUNA_P3_LOLA_PATH = $lola
# Traverse target for required navigation (default: the geographic south pole on Shackleton's rim).
$env:LUNA_NAV_TARGET_LAT = "$NavTargetLat"; $env:LUNA_NAV_TARGET_LON = "$NavTargetLon"
# Every member must serve NASA data: any MOCK input makes an option infeasible.
$env:LUNA_REQUIRE_REAL = '1'
Write-Host "NASA data mode: Person 1 $Person1Dem DEM ($env:LUNA_P1_CANDIDATE_STRATEGY candidates), Person 2 Horizons + LOLA horizon, Person 3 LOLA routes to ($NavTargetLat, $NavTargetLon). Planning can take minutes per request."
if ($GeminiModel) { $env:GEMINI_MODEL = $GeminiModel }
$env:LUNA_GEMINI_LANG = $GeminiLang
if ($env:GEMINI_API_KEY -and $env:GEMINI_API_KEY -match '^[\x21-\x7E]+$') { Write-Host "Gemini: ON (model $(if ($env:GEMINI_MODEL) { $env:GEMINI_MODEL } else { 'gemini-3.5-flash-lite' }), summary language $GeminiLang)" }
elseif ($env:GEMINI_API_KEY) { Write-Host 'Gemini: OFF (GEMINI_API_KEY is not a real key; paste the key from Google AI Studio)' }
else { Write-Host 'Gemini: OFF (set $env:GEMINI_API_KEY to enable)' }
& (Join-Path $PSScriptRoot 'start_integrated.ps1') -Port $Port
