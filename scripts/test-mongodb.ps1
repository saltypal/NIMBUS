[CmdletBinding()]
param(
    [string]$Uri = 'mongodb://127.0.0.1:27017',
    [string]$Database = 'nimbus_dependency_smoke'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Local Python environment is absent. Run .\scripts\bootstrap-local.ps1 first.'
}

$testCode = @'
import os
from pymongo import MongoClient

uri = os.environ["NIMBUS_TEST_MONGO_URI"]
database_name = os.environ["NIMBUS_TEST_MONGO_DATABASE"]
client = MongoClient(uri, serverSelectionTimeoutMS=3000)
client.admin.command("ping")
database = client[database_name]
collection = database["ping_records"]
collection.delete_many({})
collection.insert_one({"kind": "dependency_smoke", "value": 1})
record = collection.find_one({"kind": "dependency_smoke"})
if record is None or record["value"] != 1:
    raise SystemExit("MongoDB read/write smoke test failed")
client.drop_database(database_name)
print("MongoDB dependency smoke test passed")
'@

$env:NIMBUS_TEST_MONGO_URI = $Uri
$env:NIMBUS_TEST_MONGO_DATABASE = $Database
& $pythonExe -c $testCode

