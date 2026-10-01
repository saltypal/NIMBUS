[CmdletBinding()]
param(
    [string]$Version = '8.0.16'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolsPath = Join-Path $projectRoot '.tools'
$zipPath = Join-Path $toolsPath "mongodb-windows-x86_64-$Version.zip"
$targetPath = Join-Path $toolsPath 'mongodb'
$downloadUrl = "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-$Version.zip"

New-Item -ItemType Directory -Path $toolsPath -Force | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $targetPath 'bin\mongod.exe'))) {
    $extracted = Get-ChildItem -LiteralPath $toolsPath -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'bin\mongod.exe') } |
        Select-Object -First 1
    if (-not $extracted) {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath
        Expand-Archive -LiteralPath $zipPath -DestinationPath $toolsPath -Force
        $extracted = Get-ChildItem -LiteralPath $toolsPath -Directory |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'bin\mongod.exe') } |
            Select-Object -First 1
    }
    if (-not $extracted) {
        throw 'Archive did not contain a mongod.exe binary.'
    }
    if (Test-Path -LiteralPath $targetPath) {
        Remove-Item -LiteralPath $targetPath -Recurse -Force
    }
    Move-Item -LiteralPath $extracted.FullName -Destination $targetPath
}

& (Join-Path $targetPath 'bin\mongod.exe') --version
