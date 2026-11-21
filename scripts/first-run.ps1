# first-run.ps1 - Initial environment setup
# Runs once after installation

param(
    [string]$InstallDir = $env:USERPROFILE + '\.synap-forge',
    [string]$UserTag = 'Operator',
    [string]$OnlineMode = 'standalone'   # 'standalone' or 'pending_lyra' (from §36.1 wizard Page B)
)

Write-Host "🔥 Synap-Forge Meena Edition - First Run Setup" -ForegroundColor Cyan
Write-Host ""

# Create required directories
$dirs = @(
    "$InstallDir\logs",
    "$InstallDir\temp",
    "$InstallDir\SynapForge\state",
    "$InstallDir\SynapForge\config",
    "$InstallDir\SynapForge\data",
    "$InstallDir\SynapForge\memory"
)

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  ✓ Created: $dir" -ForegroundColor Green
    }
}

# Target .env destination inside SynapForge
$envFile = Join-Path $InstallDir 'SynapForge\.env'
$template = Join-Path $InstallDir 'SynapForge\config\.env.template'
if (-not (Test-Path $template)) {
    $template = Join-Path $InstallDir 'config\.env.template'
}

if (Test-Path $template -and -not (Test-Path $envFile)) {
    Write-Host "  ✓ Creating default .env at $envFile..." -ForegroundColor Green
    Copy-Item $template $envFile -Force
    if ($UserTag) {
        (Get-Content $envFile) -replace '^USER_TAG=.*$', "USER_TAG=$UserTag" | Set-Content $envFile
    }
}

# Create node_preferences.json (§36.1: mode field drives Island Mode vs VTX opt-in)
$prefPath = Join-Path $InstallDir 'SynapForge\state\node_preferences.json'
if (-not (Test-Path $prefPath)) {
    Write-Host "  ✓ Creating initial node_preferences.json (mode: $OnlineMode)..." -ForegroundColor Green
    $prefObj = [ordered]@{
        mode        = $OnlineMode          # 'standalone' (Island Mode) or 'pending_lyra' (VTX opt-in)
        api_access  = $false
        mesh_access = $false
        user_tag    = $UserTag
    }
    $prefObj | ConvertTo-Json | Set-Content $prefPath -Encoding UTF8
}

# Check Tailscale
if (Get-Command tailscale -ErrorAction SilentlyContinue) {
    Write-Host "  ✓ Tailscale detected" -ForegroundColor Green
} else {
    Write-Host "  ⚠️ Tailscale not detected - running in local-only mode" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✅ First run setup complete!" -ForegroundColor Green
