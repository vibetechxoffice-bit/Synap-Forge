# cleanup.ps1 - Pre-uninstall cleanup

param(
    [string]$InstallDir = $env:USERPROFILE + '\.synap-forge'
)

Write-Host "🧹 Synap-Forge Uninstaller - Cleaning up..." -ForegroundColor Yellow

# Only target processes that exist within our specific directory tree
$targetDir = $InstallDir.ToLower()

$procs = @(
    @{name='llama-server'; exe='llama-server.exe'}
    @{name='python'; exe='synap_server.py'}
    @{name='studio64'; exe='studio64.exe'}
)

foreach ($p in $procs) {
    Get-Process -Name $p.name -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -like "*$targetDir*"
    } | Stop-Process -Force -ErrorAction SilentlyContinue
}

# Remove PID if it exists
$pidFile = "$InstallDir\synap.pid"
if (Test-Path $pidFile) { Remove-Item $pidFile -Force }

Write-Host "✅ Cleanup complete!" -ForegroundColor Green
