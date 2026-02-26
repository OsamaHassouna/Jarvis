# install.ps1 — Compile, package, and install the Jarvis VS Code extension.
# Run whenever you want to push code changes to the installed extension:
#   cd vscode-extension
#   .\install.ps1
# Then reload VS Code: Ctrl+Shift+P -> Developer: Reload Window

Set-Location $PSScriptRoot

Write-Host "Compiling TypeScript..." -ForegroundColor Cyan
npm run compile
if ($LASTEXITCODE -ne 0) { Write-Host "Compile failed." -ForegroundColor Red; exit 1 }

Write-Host "Packaging VSIX..." -ForegroundColor Cyan
npx @vscode/vsce package --no-dependencies --allow-missing-repository --out jarvis-assistant-0.3.0.vsix
if ($LASTEXITCODE -ne 0) { Write-Host "Package failed." -ForegroundColor Red; exit 1 }

Write-Host "Installing extension..." -ForegroundColor Cyan
code --install-extension jarvis-assistant-0.3.0.vsix --force
if ($LASTEXITCODE -ne 0) { Write-Host "Install failed." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Done. Reload VS Code to see changes:" -ForegroundColor Green
Write-Host "  Ctrl+Shift+P -> Developer: Reload Window" -ForegroundColor Yellow
