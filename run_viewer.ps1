# run_viewer.ps1 - open the workbench on an existing GLB + BOM database (no STEP conversion)
param(
    [string]$Glb    = "cad_model.glb",
    [string]$Sqlite = "bom_data.sqlite",
    [int]$Port      = 8000
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

foreach ($f in $Glb, $Sqlite) {
    if (-not (Test-Path $f)) { Write-Error "Missing '$f'. Run run_pipeline.ps1 first to build it from the STEP file." }
}
foreach ($f in $Glb, $Sqlite) {
    if ((Resolve-Path $f).Path -notlike "$PSScriptRoot*") { Write-Error "'$f' must be inside the project folder so the local server can serve it." }
}
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }

$rel = { param($p) [uri]::EscapeDataString((Resolve-Path -Relative $p).TrimStart('.\').Replace('\', '/')) }
$Url = "http://localhost:$Port/index.html?glb=$(& $rel $Glb)&db=$(& $rel $Sqlite)"

$Server = Start-Job -ScriptBlock { param($Py, $Dir, $Port) Set-Location $Dir; & $Py -m http.server $Port } -ArgumentList $Python, $PSScriptRoot, $Port
Start-Sleep -Seconds 2
Write-Host "Opening $Url" -ForegroundColor Green
Start-Process $Url
Write-Host "Server running. Press [CTRL + C] to stop." -ForegroundColor Gray
try { while ($true) { Start-Sleep -Seconds 1 } }
finally { Stop-Job $Server; Remove-Job $Server }
