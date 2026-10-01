[CmdletBinding()]
param(
    [switch]$InstallManagedChromium
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $projectRoot '.tools\browser-check'
$manifestPath = Join-Path $toolRoot 'package.json'
$cliPath = Join-Path $toolRoot 'node_modules\.bin\playwright-cli.cmd'
$chromePath = 'C:\Program Files\Google\Chrome\Application\chrome.exe'

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'npm is required for the isolated browser-check environment.'
}

New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
@'
{
  "name": "nimbus-browser-check",
  "private": true,
  "version": "0.1.0",
  "devDependencies": {
    "@playwright/cli": "0.1.22",
    "playwright": "1.57.0"
  }
}
'@ | Set-Content -LiteralPath $manifestPath -Encoding utf8

Push-Location $toolRoot
try {
    & npm.cmd install
    if ($LASTEXITCODE -ne 0) { throw 'Browser tooling installation failed.' }
    if ($InstallManagedChromium) {
        & (Join-Path $toolRoot 'node_modules\.bin\playwright.cmd') install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Managed Chromium download failed.' }
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $cliPath)) {
    throw "Playwright CLI install did not create $cliPath"
}
if (-not (Test-Path -LiteralPath $chromePath) -and -not $InstallManagedChromium) {
    throw 'Google Chrome was not found. Re-run with -InstallManagedChromium to download Playwright Chromium.'
}

Write-Host "Browser CLI ready: $cliPath"
if (Test-Path -LiteralPath $chromePath) {
    Write-Host "Headless browser channel: $chromePath"
    Write-Host "Example: $cliPath open http://127.0.0.1:4173 --browser chrome"
}
