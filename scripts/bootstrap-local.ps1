[CmdletBinding()]
param(
    [switch]$Recreate
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot '.venv'
$pythonExe = Join-Path $venvPath 'Scripts\python.exe'

if ($Recreate -and (Test-Path -LiteralPath $venvPath)) {
    $resolvedProject = (Resolve-Path -LiteralPath $projectRoot).ProviderPath
    $venvEntry = Get-Item -LiteralPath $venvPath -Force
    $resolvedVenv = (Resolve-Path -LiteralPath $venvPath).ProviderPath
    if (($venvEntry.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        $resolvedVenv -ne (Join-Path $resolvedProject '.venv')) {
        throw 'Refusing to remove an environment outside the project-owned .venv directory.'
    }
    Remove-Item -LiteralPath $venvPath -Recurse -Force
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    # The Windows launcher can expose a uv-managed interpreter with a vendor
    # qualifier instead of the short `-3.11` selector.
    $python311 = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $python311 = & py -V:Astral/CPython3.11 -c "import sys; print(sys.executable)" 2>$null
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Python 3.11 is required. Install it, then re-run this script.'
    }
    & $python311 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw 'Local environment creation failed.' }
}

& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
$installTarget = $projectRoot + '[dev]'
& $pythonExe -m pip install -e $installTarget
if ($LASTEXITCODE -ne 0) { throw 'Local package installation failed.' }
& $pythonExe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Local dependency compatibility check failed.' }
& $pythonExe -m pip freeze --exclude-editable | Set-Content -LiteralPath (Join-Path $projectRoot 'requirements\local.lock.txt') -Encoding utf8

Write-Host "Local environment ready: $pythonExe"
Write-Host 'Run tests with: .\.venv\Scripts\python.exe -m pytest'
