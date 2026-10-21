# Run explicitly after installing Docker Desktop and configuring .env.
# This script may download Docker images; it does not install JDK/Node or start app terminals.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
& (Join-Path $PSScriptRoot 'load-env.ps1')

foreach ($setting in @('DB_PASSWORD','MYSQL_ROOT_PASSWORD','REDIS_PASSWORD','MINIO_SECRET_KEY','QDRANT_API_KEY')) {
    $value = [Environment]::GetEnvironmentVariable($setting, 'Process')
    if (-not $value -or $value.StartsWith('change-')) { throw "Configure $setting in .env first." }
}
if ($env:DB_USERNAME -ne $env:MYSQL_APP_USER) { throw 'DB_USERNAME must match MYSQL_APP_USER for this Compose setup.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop / docker CLI is not available.' }

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    & docker compose --env-file .env @ComposeArgs
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose command failed. Check the preceding diagnostic output.' }
}

Push-Location $projectRoot
try {
    & docker info | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop with Linux containers first.' }
    Invoke-Compose @('config','--quiet')
    # Match the existing Bash bootstrap: RocketMQ runs as uid 3000 in its named volumes.
    Invoke-Compose @('run','--rm','--no-deps','--user','root','--entrypoint','sh','rmqbroker','-c','mkdir -p /home/rocketmq/store /home/rocketmq/logs && chown -R 3000:3000 /home/rocketmq/store /home/rocketmq/logs')
    Invoke-Compose @('up','-d','--wait','--wait-timeout','120')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $listing = & docker compose --env-file .env exec -T rmqbroker sh -c '$ROCKETMQ_HOME/bin/mqadmin clusterList -n rmqnamesrv:9876' 2>$null
        if ($LASTEXITCODE -eq 0 -and ($listing -join "`n") -match 'broker-a') { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'RocketMQ broker did not register. Inspect: docker compose logs rmqbroker' }
    $topics = @('video-analysis-topic','video-analysis-dead-topic','learning-parse')
    if ($env:ROCKETMQ_ANALYSIS_TOPIC) { $topics[0] = $env:ROCKETMQ_ANALYSIS_TOPIC }
    if ($env:ROCKETMQ_ANALYSIS_DEAD_TOPIC) { $topics[1] = $env:ROCKETMQ_ANALYSIS_DEAD_TOPIC }
    foreach ($topic in $topics) {
        if ($topic -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid RocketMQ topic name.' }
        $topicCommand = '$ROCKETMQ_HOME/bin/mqadmin updateTopic -n rmqnamesrv:9876 -c DefaultCluster -t ' + $topic
        Invoke-Compose @('exec','-T','rmqbroker','sh','-c',$topicCommand)
    }
    Invoke-Compose @('ps')
    Write-Output 'Infrastructure started. Follow docs/course-workbench-v2/SETUP-WINDOWS.md to run tests and start the apps.'
} finally {
    Pop-Location
}
