# Local verification settings. Secrets stay in ignored .learning-work, never in reports.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$projectPythonRoot = 'D:\miniconda3\envs\dovideo-learning'
$projectPython = Join-Path $projectPythonRoot 'python.exe'
if (-not (Test-Path -LiteralPath $projectPython -PathType Leaf)) {
    throw "Missing project Python environment: $projectPython"
}
$pythonIdentity = @'
import json
import sys
print(json.dumps({
    "executable": sys.executable,
    "prefix": sys.prefix,
    "major": sys.version_info.major,
    "minor": sys.version_info.minor,
}))
'@ | & $projectPython -
if ($LASTEXITCODE -ne 0) { throw 'Unable to validate the project Python environment.' }
$pythonInfo = $pythonIdentity | ConvertFrom-Json
if ($pythonInfo.prefix -ne $projectPythonRoot -or $pythonInfo.major -ne 3 -or $pythonInfo.minor -ne 12) {
    throw "Unexpected project Python identity: $pythonIdentity"
}
$env:LEARNING_PYTHON = $projectPython
# Ensure unqualified python/pip/uvicorn in this PowerShell resolve to the same
# dedicated environment. Use `python -m pip` for installs even after this.
$pathEntries = @($projectPythonRoot, (Join-Path $projectPythonRoot 'Scripts'))
$existingPath = $env:PATH -split ';' | Where-Object {
    $_ -and $_ -ne $projectPythonRoot -and $_ -ne (Join-Path $projectPythonRoot 'Scripts')
}
$env:PATH = (@($pathEntries) + @($existingPath)) -join ';'
& (Join-Path $PSScriptRoot 'load-env.ps1')
$runtimeDirectory = Join-Path $projectRoot '.learning-work'
New-Item -ItemType Directory -Force $runtimeDirectory | Out-Null
$tokenFile = Join-Path $runtimeDirectory 'service-token.txt'
if ($env:LEARNING_SERVICE_TOKEN -and $env:LEARNING_SERVICE_TOKEN.Length -ge 32) {
    # Keep the explicitly configured Java/Python shared token from .env.
} elseif (-not (Test-Path -LiteralPath $tokenFile)) {
    # Windows PowerShell 5.1 runs on .NET Framework, which does not provide
    # RandomNumberGenerator.GetBytes(int) or Convert.ToHexString().
    $tokenBytes = New-Object byte[] 32
    $randomNumberGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $randomNumberGenerator.GetBytes($tokenBytes)
    } finally {
        $randomNumberGenerator.Dispose()
    }
    ($tokenBytes | ForEach-Object { $_.ToString('x2') }) -join '' |
        Set-Content -LiteralPath $tokenFile -NoNewline
    $env:LEARNING_SERVICE_TOKEN = Get-Content -LiteralPath $tokenFile -Raw
} else {
    $env:LEARNING_SERVICE_TOKEN = Get-Content -LiteralPath $tokenFile -Raw
}
$env:LEARNING_DATABASE_URL = 'mysql+pymysql://' + [Uri]::EscapeDataString($env:DB_USERNAME) + ':' + [Uri]::EscapeDataString($env:DB_PASSWORD) + '@127.0.0.1:3307/media_db?charset=utf8mb4'
$env:LEARNING_PARSING_ENABLED = 'true'
$env:LEARNING_PARSING_AUTO_ENQUEUE = 'true'
$env:SERVER_PORT = '9090'
$env:LEARNING_JAVA_URL = 'http://127.0.0.1:9090'
$env:LEARNING_PYTHON_URL = 'http://127.0.0.1:8091'
$env:LEARNING_MINIO_ENDPOINT = '127.0.0.1:9000'
$env:LEARNING_MINIO_ACCESS_KEY = $env:MINIO_ACCESS_KEY
$env:LEARNING_MINIO_SECRET_KEY = $env:MINIO_SECRET_KEY
$env:LEARNING_MINIO_BUCKET = $env:MINIO_BUCKET
$env:LEARNING_MINIO_SECURE = 'false'
$env:DOCLING_ARTIFACTS_PATH = Join-Path $projectRoot '.learning-models'
$env:LEARNING_QDRANT_URL = if ($env:LEARNING_QDRANT_URL) { $env:LEARNING_QDRANT_URL } else { 'http://127.0.0.1:6333' }
$env:LEARNING_QDRANT_API_KEY = if ($env:LEARNING_QDRANT_API_KEY) { $env:LEARNING_QDRANT_API_KEY } else { $env:QDRANT_API_KEY }
$env:LEARNING_QDRANT_COLLECTION = if ($env:LEARNING_QDRANT_COLLECTION) { $env:LEARNING_QDRANT_COLLECTION } else { 'course_knowledge_bge_m3_d1024_v1' }
$env:LEARNING_EMBEDDING_PROVIDER = 'local_bge_m3'
$env:LEARNING_EMBEDDING_MODEL_PATH = Join-Path $projectRoot '.learning-models\bge-m3'
$embeddingRevisionFile = Join-Path $projectRoot '.learning-models\bge-m3.revision.txt'
if (-not (Test-Path -LiteralPath $env:LEARNING_EMBEDDING_MODEL_PATH -PathType Container)) {
    throw "Missing BGE-M3 model directory: $env:LEARNING_EMBEDDING_MODEL_PATH"
}
if (-not (Test-Path -LiteralPath $embeddingRevisionFile -PathType Leaf)) {
    throw "Missing BGE-M3 revision file: $embeddingRevisionFile"
}
$env:LEARNING_EMBEDDING_MODEL_REVISION = (Get-Content -LiteralPath $embeddingRevisionFile -Raw).Trim()
$env:LEARNING_EMBEDDING_DIMENSION = '1024'
$env:LEARNING_EMBEDDING_BATCH_SIZE = if ($env:LEARNING_EMBEDDING_BATCH_SIZE) { $env:LEARNING_EMBEDDING_BATCH_SIZE } else { '8' }
$env:LEARNING_EMBEDDING_DEVICE = if ($env:LEARNING_EMBEDDING_DEVICE) { $env:LEARNING_EMBEDDING_DEVICE } else { 'cpu' }
# Dependencies are installed in the dedicated dovideo-learning environment.
# Keep only the repository root on PYTHONPATH; a legacy .python-deps directory
# can contain incompatible compiled packages and must not shadow that environment.
$env:PYTHONPATH = $projectRoot
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:LEARNING_WORK_DIR = $runtimeDirectory
