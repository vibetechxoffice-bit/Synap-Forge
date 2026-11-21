param(
    [string]$AppDir = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$ShortcutName = "Synap-Forge"
)

$batPath = Join-Path $AppDir "launcher.bat"
$exePath = Join-Path $AppDir "Synap-Forge.exe"
$iconPath = Join-Path $AppDir "icon.ico"

# Use standalone EXE if present; otherwise launcher.bat
if (Test-Path $exePath) {
    $targetPath = $exePath
} elseif (Test-Path $batPath) {
    $targetPath = $batPath
} else {
    Write-Error "Neither launcher.bat nor Synap-Forge.exe found at $AppDir"
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "$ShortcutName.lnk"

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnkPath)
$sc.TargetPath = $targetPath
$sc.WorkingDirectory = $AppDir
if (Test-Path $iconPath) { $sc.IconLocation = $iconPath }
$sc.WindowStyle = 7      # Minimized to prevent flashing console windows
$sc.Description = "Synap-Forge AI Server Launcher"
$sc.Save()

Write-Host "Shortcut deployed successfully: $lnkPath"
