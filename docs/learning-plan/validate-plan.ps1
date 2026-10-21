param(
    [string]$PlanRoot = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
$planDirectory = (Resolve-Path -LiteralPath $PlanRoot).Path
$statusPath = Join-Path $planDirectory 'STATUS.json'
$plan = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
$taskMap = @{}
$allowedStates = @('TODO', 'IN_PROGRESS', 'VERIFY_PENDING', 'BLOCKED', 'DONE')
$allowedChecks = @('PASS', 'FAIL', 'NOT_RUN', 'BLOCKED')

function Assert-PlanFile([string]$RelativePath) {
    if ([string]::IsNullOrWhiteSpace($RelativePath)) { throw 'Missing evidence/file path.' }
    $candidate = Join-Path $planDirectory $RelativePath
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Missing file: $RelativePath"
    }
}

foreach ($task in $plan.tasks) {
    if ($taskMap.ContainsKey($task.id)) { throw "Duplicate task: $($task.id)" }
    if ($task.status -notin $allowedStates) { throw "Invalid task state: $($task.id)" }
    Assert-PlanFile $task.card
    $taskMap[$task.id] = $task
}

$visitState = @{}
function Visit-Task([string]$TaskId) {
    if (-not $taskMap.ContainsKey($TaskId)) { throw "Unknown dependency: $TaskId" }
    if ($visitState[$TaskId] -eq 1) { throw "Dependency cycle: $TaskId" }
    if ($visitState[$TaskId] -eq 2) { return }
    $visitState[$TaskId] = 1
    foreach ($dependency in $taskMap[$TaskId].dependsOn) { Visit-Task $dependency }
    $visitState[$TaskId] = 2
}
foreach ($task in $plan.tasks) { Visit-Task $task.id }

$running = @($plan.tasks | Where-Object { $_.status -eq 'IN_PROGRESS' })
if ($running.Count -gt 1) { throw 'More than one IN_PROGRESS task.' }
if ($running.Count -eq 1 -and $plan.currentTaskId -ne $running[0].id) {
    throw 'currentTaskId does not match the running task.'
}
if ($plan.currentTaskId -and -not $taskMap.ContainsKey($plan.currentTaskId)) {
    throw 'currentTaskId does not exist.'
}

foreach ($task in $plan.tasks) {
    if ($task.status -in @('IN_PROGRESS', 'DONE')) {
        foreach ($dependency in $task.dependsOn) {
            if ($taskMap[$dependency].status -ne 'DONE') {
                throw "$($task.id) started/completed before dependency $dependency."
            }
        }
    }
    foreach ($check in $task.checks) {
        if ($check.status -notin $allowedChecks) { throw "Invalid check state: $($task.id)" }
        foreach ($evidence in $check.evidence) { Assert-PlanFile $evidence }
    }
    if ($task.status -eq 'DONE') {
        Assert-PlanFile $task.handoff
        $requiredChecks = @($task.checks | Where-Object { $_.required -eq $true })
        if ($requiredChecks.Count -eq 0) { throw "No required validation recorded: $($task.id)" }
        foreach ($check in $requiredChecks) {
            if ($check.status -ne 'PASS') { throw "Required validation not passed: $($task.id)" }
            if (@($check.evidence).Count -eq 0) { throw "Required validation has no evidence: $($task.id)" }
        }
    }
}

if ($plan.nextTaskId) {
    if (-not $taskMap.ContainsKey($plan.nextTaskId)) { throw 'nextTaskId does not exist.' }
    $nextTask = $taskMap[$plan.nextTaskId]
    if ($nextTask.status -ne 'TODO') { throw 'nextTaskId must identify a TODO task.' }
    foreach ($dependency in $nextTask.dependsOn) {
        if ($taskMap[$dependency].status -ne 'DONE') { throw 'nextTaskId has an unfinished dependency.' }
    }
}

foreach ($gate in $plan.gates) {
    if ($gate.status -notin $allowedChecks) { throw "Invalid gate state: $($gate.id)" }
    foreach ($taskId in $gate.taskIds) {
        if (-not $taskMap.ContainsKey($taskId)) { throw "Unknown gate task: $taskId" }
        if ($gate.status -eq 'PASS' -and $taskMap[$taskId].status -ne 'DONE') {
            throw "Gate passed before task completion: $($gate.id) / $taskId"
        }
    }
    foreach ($evidence in $gate.evidence) { Assert-PlanFile $evidence }
    if ($gate.status -eq 'PASS' -and @($gate.evidence).Count -eq 0) {
        throw "Passed gate has no evidence: $($gate.id)"
    }
}

$markdownFiles = @(Get-ChildItem -LiteralPath $planDirectory -Filter '*.md' -Recurse -File)
foreach ($file in $markdownFiles) {
    $content = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
    if (([regex]::Matches($content, '(?m)^```').Count % 2) -ne 0) {
        throw "Unbalanced code fences: $($file.FullName)"
    }
    foreach ($match in [regex]::Matches($content, '\]\(([^)]+)\)')) {
        $link = $match.Groups[1].Value
        if ($link -match '^(https?:|#|mailto:)') { continue }
        $linkPath = ($link -split '#', 2)[0]
        $target = Join-Path $file.DirectoryName $linkPath
        if (-not (Test-Path -LiteralPath $target)) {
            throw "Broken Markdown link: $($file.Name) -> $link"
        }
    }
}

[pscustomobject]@{
    Tasks = @($plan.tasks).Count
    Gates = @($plan.gates).Count
    MarkdownFiles = $markdownFiles.Count
    DoneTasks = @($plan.tasks | Where-Object { $_.status -eq 'DONE' }).Count
    NextTask = $plan.nextTaskId
    Result = 'PASS: plan structure only; business tests are not executed.'
}
