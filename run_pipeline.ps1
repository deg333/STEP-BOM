# run_pipeline.ps1
#   -KeepFasteners        keep small high-count parts in the model (default: remove them)
#   -FastenerMinCount N   instances needed to count as a fastener (default 12)
#   -FastenerMaxVolume V  max bounding-box volume in mm^3 of a fastener (default 8000)
#   -MaxDepth N           hierarchy levels to keep, root = 1; assemblies at level N are merged
#                         into one node (default 0 = full hierarchy)
param(
    [switch]$KeepFasteners,
    [int]$FastenerMinCount = 12,
    [double]$FastenerMaxVolume = 8000,
    [int]$MaxDepth = 0
)
$ErrorActionPreference = "Stop"

$StepInputFile     = "factory_assembly.STEP"
$GlbOutputFile    = "cad_model.glb"
$SQLiteOutputFile  = "bom_data.sqlite"
$ServerPort        = 8000

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " LAUNCHING VALUE ENGINEERING 3D WORKBENCH PIPELINE " -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan

# 1. Environment Verification (project venv holds cadquery-ocp; see vs\wheelhouse.zip for offline wheels)
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Project venv missing. Run: py -3.14 -m venv .venv ; .venv\Scripts\python -m pip install cadquery-ocp trimesh"
}
Set-Location $PSScriptRoot

# 2. Compile STEP data
Write-Host "Processing STEP file geometry & generating relational SQLite data structures..." -ForegroundColor Yellow
if (-not (Test-Path $StepInputFile)) {
    Write-Error "Input CAD step file missing! Please place '$StepInputFile' in this directory."
}

$BuildArgs = @("--input", $StepInputFile, "--glb", $GlbOutputFile, "--sqlite", $SQLiteOutputFile,
               "--fastener-min-count", $FastenerMinCount, "--fastener-max-volume", $FastenerMaxVolume,
               "--max-depth", $MaxDepth)
if ($KeepFasteners) { $BuildArgs += "--keep-fasteners" }
& $Python build_zero_query_assets.py @BuildArgs
if ($LASTEXITCODE -ne 0) { Write-Error "Asset build failed (exit code $LASTEXITCODE)." }

# 3. Boot Local Web Server
Write-Host "Starting background local HTTP host layer on port $ServerPort..." -ForegroundColor Yellow
$ServerJob = Start-Job -ScriptBlock {
    param($Port, $Py, $Dir)
    Set-Location $Dir
    & $Py -m http.server $Port
} -ArgumentList $ServerPort, $Python, $PSScriptRoot

Start-Sleep -Seconds 2

# 4. Open Application Viewport
$TargetUrl = "http://localhost:$ServerPort/index.html"
Write-Host "Launching web browser workspace environment: $TargetUrl" -ForegroundColor Green
Start-Process $TargetUrl

Write-Host "Pipeline server running successfully. Press [CTRL + C] in this window to terminate server." -ForegroundColor Gray
try { while ($true) { Start-Sleep -Seconds 1 } }
finally {
    Write-Host "`nTerminating background server tasks..." -ForegroundColor Yellow
    Stop-Job $ServerJob ; Remove-Job $ServerJob
}