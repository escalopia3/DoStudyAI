$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'learning-live-env.ps1')

$identity = @'
import json, sys
print(json.dumps({
    "executable": sys.executable,
    "prefix": sys.prefix,
    "version": sys.version.split()[0],
}))
'@ | & $env:LEARNING_PYTHON -
if ($LASTEXITCODE -ne 0) { throw 'Project Python identity check failed.' }

$packages = @'
import importlib.metadata as metadata, json
names = ["docling", "rapidocr", "onnxruntime", "torch", "transformers",
         "fastapi", "uvicorn", "sqlalchemy", "alembic", "pymysql", "httpx", "minio",
         "sentence-transformers"]
result = {}
for name in names:
    try: result[name] = metadata.version(name)
    except metadata.PackageNotFoundError: result[name] = None
print(json.dumps(result))
'@ | & $env:LEARNING_PYTHON -
if ($LASTEXITCODE -ne 0) { throw 'Project package check failed.' }

$modelRoot = Join-Path $projectRoot '.learning-models'
$legacyDependencies = Join-Path $projectRoot '.python-deps'
[pscustomobject]@{
    Python = ($identity | ConvertFrom-Json).executable
    Version = ($identity | ConvertFrom-Json).version
    Prefix = ($identity | ConvertFrom-Json).prefix
    PipHealthy = ((& $env:LEARNING_PYTHON -m pip check 2>&1) -join "`n")
    ModelsDirectory = $modelRoot
    ModelsPresent = (Test-Path -LiteralPath $modelRoot -PathType Container)
    BgeM3Present = (Test-Path -LiteralPath (Join-Path $modelRoot 'bge-m3') -PathType Container)
    LegacyPythonDepsPresent = (Test-Path -LiteralPath $legacyDependencies)
    Packages = ($packages | ConvertFrom-Json | ConvertTo-Json -Compress)
} | Format-List
