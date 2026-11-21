param(
    [string]$AppDir = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$ShortcutName = "Synap-Forge"
)

$batPath = Join-Path $AppDir "launcher.bat"
$iconPath = Join-Path $AppDir "icon.ico"

if (-not (Test-Path $batPath)) {
    Write-Error "launcher.bat not found at $batPath"
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "$ShortcutName.lnk"

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnkPath)
$sc.TargetPath = $batPath
$sc.WorkingDirectory = $AppDir
if (Test-Path $iconPath) { $sc.IconLocation = $iconPath }
$sc.WindowStyle = 7      # minimized
$sc.Description = "Synap-Forge"
$sc.Save()

Write-Host "Shortcut deployed: $lnkPath"
