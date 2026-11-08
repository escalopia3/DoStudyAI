$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$langGraph = (Get-Command langgraph -ErrorAction Stop).Source

& $langGraph dev --no-browser @args
exit $LASTEXITCODE
