# install.ps1
# One-time setup: packages the Jarvis extension and installs it into VS Code.
# After this runs, Jarvis auto-starts every time VS Code opens.
# Run with: .\install.ps1

$ErrorActionPreference = "Stop"

$ExtDir    = $PSScriptRoot
$JarvisDir = Split-Path $ExtDir -Parent

Write-Host ""
Write-Host "=== Jarvis VS Code Extension Installer ===" -ForegroundColor Cyan
Write-Host ""

# 1 - Compile TypeScript
Write-Host "[1/4] Compiling TypeScript..." -ForegroundColor Yellow
Set-Location $ExtDir
npm run compile 2>&1 | Out-Null
Write-Host "      Done." -ForegroundColor Green

# 2 - Install vsce if not present
Write-Host "[2/4] Checking vsce (packager)..." -ForegroundColor Yellow
if (-not (Get-Command "vsce" -ErrorAction SilentlyContinue)) {
    Write-Host "      Installing @vscode/vsce globally..." -ForegroundColor Yellow
    npm install -g @vscode/vsce 2>&1 | Out-Null
}
Write-Host "      Done." -ForegroundColor Green

# 3 - Package the extension
Write-Host "[3/4] Packaging extension..." -ForegroundColor Yellow
$null = cmd /c "vsce package --no-dependencies --out jarvis-assistant.vsix 2>&1"
Write-Host "      Done." -ForegroundColor Green

# 4 - Install into VS Code
Write-Host "[4/4] Installing into VS Code..." -ForegroundColor Yellow
code --install-extension "$ExtDir\jarvis-assistant.vsix" --force 2>&1 | Out-Null
Write-Host "      Done." -ForegroundColor Green

# 5 - Write jarvis.serverPath into VS Code user settings
Write-Host ""
Write-Host "--- Configuring jarvis.serverPath ---" -ForegroundColor Cyan

$SettingsPath = "$env:APPDATA\Code\User\settings.json"
$EscapedPath  = $JarvisDir.Replace('\', '\\')
$NewEntry     = "`"jarvis.serverPath`": `"$EscapedPath`""

if (-not (Test-Path $SettingsPath)) {
    Set-Content -Path $SettingsPath -Value "{`n    $NewEntry`n}" -Encoding UTF8
} else {
    $raw = Get-Content $SettingsPath -Raw -Encoding UTF8

    if ($raw -match '"jarvis\.serverPath"') {
        $raw = $raw -replace '"jarvis\.serverPath"\s*:\s*"[^"]*"', $NewEntry
        Set-Content -Path $SettingsPath -Value $raw -Encoding UTF8
    } else {
        $raw = $raw.TrimEnd()
        if ($raw.EndsWith('{')) {
            $raw = "{`n    $NewEntry`n}"
        } else {
            $raw = $raw.Substring(0, $raw.LastIndexOf('}'))
            $raw = $raw.TrimEnd().TrimEnd(',')
            $raw += ",`n    $NewEntry`n}"
        }
        Set-Content -Path $SettingsPath -Value $raw -Encoding UTF8
    }
}

Write-Host "      jarvis.serverPath = $JarvisDir" -ForegroundColor Green
Write-Host ""
Write-Host "=== All done! ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Restart VS Code - Jarvis will start automatically." -ForegroundColor White
Write-Host "Press Ctrl+Shift+J to open the panel." -ForegroundColor White
Write-Host "Use 'Jarvis: Restart Server' from the command palette if needed." -ForegroundColor White
Write-Host ""
