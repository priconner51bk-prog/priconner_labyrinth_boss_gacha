param(
    [switch]$Full
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$reportDir = Join-Path $root 'artifacts'
$reportPath = Join-Path $reportDir 'gacha-test-report.json'
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

$testArgs = if ($Full) {
    @('-m', 'pytest', '-q', 'tests')
} else {
    @('-m', 'pytest', '-q',
        'tests/test_boss_gacha_controller.py',
        'tests/test_boss_gacha_runner.py',
        'tests/test_boss_gacha_live_flow.py',
        'tests/test_boss_gacha_live_workflow.py',
        'tests/test_guild_selection.py',
        'tests/test_guild_scroll.py',
        'tests/test_live_cli_limits.py')
}

$started = Get-Date
& python @testArgs 2>&1 | Tee-Object -Variable output
$exitCode = $LASTEXITCODE
$report = [ordered]@{
    kind = 'gacha-automated-tests'
    started_at = $started.ToUniversalTime().ToString('o')
    finished_at = (Get-Date).ToUniversalTime().ToString('o')
    full_suite = [bool]$Full
    exit_code = $exitCode
    output = ($output -join "`n")
    live_input = $false
}
$report | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -Path $reportPath
exit $exitCode
