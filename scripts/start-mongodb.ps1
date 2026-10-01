[CmdletBinding()]
param(
    [int]$Port = 27017
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$mongod = Join-Path $projectRoot '.tools\mongodb\bin\mongod.exe'
$dataPath = Join-Path $projectRoot '.data\mongodb'
$logPath = Join-Path $projectRoot '.data\mongodb.log'

if (-not (Test-Path -LiteralPath $mongod)) {
    throw 'MongoDB binary is absent. Run .\scripts\install-mongodb-local.ps1 first.'
}

New-Item -ItemType Directory -Path $dataPath -Force | Out-Null

& $mongod `
    --dbpath $dataPath `
    --bind_ip 127.0.0.1 `
    --port $Port `
    --logpath $logPath `
    --logappend

