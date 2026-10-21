param([string]$Path = (Join-Path (Split-Path $PSScriptRoot -Parent) '.env'))

# Loads literal KEY=VALUE pairs into this process. Never evaluates shell expressions.
if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw 'Missing .env. Copy .env.example to .env and fill in the local settings first.'
}
foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
    if ($trimmed -notmatch '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        throw 'Invalid .env line. Use literal KEY=VALUE entries, with optional outer quotes.'
    }
    $settingName = $Matches[1]
    $settingValue = $Matches[2].Trim()
    if ($settingValue.Length -ge 2) {
        if (($settingValue.StartsWith('"') -and $settingValue.EndsWith('"')) -or
            ($settingValue.StartsWith("'") -and $settingValue.EndsWith("'"))) {
            $settingValue = $settingValue.Substring(1, $settingValue.Length - 2)
        }
    }
    [Environment]::SetEnvironmentVariable($settingName, $settingValue, 'Process')
}
