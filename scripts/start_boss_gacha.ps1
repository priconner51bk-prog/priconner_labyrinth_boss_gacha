[CmdletBinding()]
param(
    [string]$BlueStacksPath,
    [string]$BlueStacksArgs = "--instance Nougat32",
    [string]$AdbPath,
    [string]$Serial = "127.0.0.1:5555",
    [string]$Package = "jp.co.cygames.princessconnectredive",
    [ValidateRange(1, 1000)]
    [int]$Attempts = 1000,
    [ValidateRange(1, 1000)]
    [string]$Guild,
    [string[]]$Area3Boss = @("ベノムサラマンドラ"),
    [string[]]$Area5Boss = @("ゴブリンロード"),
    [switch]$Execute,
    [int]$BootTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path

function Resolve-BlueStacksPath {
    param([string]$Configured)
    if ($Configured) {
        if (-not (Test-Path -LiteralPath $Configured -PathType Leaf)) {
            throw "BlueStacks executable not found: $Configured"
        }
        return (Resolve-Path -LiteralPath $Configured).Path
    }
    $candidates = @(
        "C:\Program Files\BlueStacks_nxt\HD-Player.exe",
        "C:\Program Files\BlueStacks\HD-Player.exe",
        "C:\Program Files (x86)\BlueStacks_nxt\HD-Player.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw "BlueStacks executable was not found. Pass -BlueStacksPath 'C:\...\HD-Player.exe'."
}

function Invoke-Adb {
    param([string[]]$Arguments)
    & $AdbPath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "ADB failed ($LASTEXITCODE): $($Arguments -join ' ')" }
}

if (-not (Test-Path -LiteralPath $AdbPath -PathType Leaf)) {
    if ($AdbPath) { throw "ADB executable was not found: $AdbPath" }
    $adbCommand = Get-Command adb -ErrorAction SilentlyContinue
    if (-not $adbCommand) { throw "ADB was not found. Install Android SDK Platform-Tools and add adb to PATH, or pass -AdbPath." }
    $AdbPath = $adbCommand.Source
}

$BlueStacks = Resolve-BlueStacksPath -Configured $BlueStacksPath
if (-not (Get-Process -Name "HD-Player" -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $BlueStacks -ArgumentList $BlueStacksArgs | Out-Null
}

$deadline = (Get-Date).AddSeconds($BootTimeoutSeconds)
$connected = $false
do {
    try {
        & $AdbPath connect $Serial 2>$null | Out-Null
        $state = (& $AdbPath -s $Serial get-state 2>$null).Trim()
        if ($state -eq "device") { $connected = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

if (-not $connected) {
    throw "ADB device did not become ready: $Serial"
}

if (-not $Execute) {
    [pscustomobject]@{
        status = "preflight_ok"
        serial = $Serial
        package = $Package
        execute = $false
    } | ConvertTo-Json -Compress
    exit 0
}

Invoke-Adb @("-s", $Serial, "shell", "monkey", "-p", $Package, "1")
$appDeadline = (Get-Date).AddSeconds($BootTimeoutSeconds)
$appRunning = $false
do {
    try {
        $appPid = (& $AdbPath -s $Serial shell pidof $Package 2>$null).Trim()
        if ($appPid) { $appRunning = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $appDeadline)
if (-not $appRunning) {
    throw "Princess Connect did not start: $Package"
}

$python = (Get-Command python -ErrorAction Stop).Source
$arguments = @("-u", "main.py", "live", "--serial", $Serial,
    "--passports", $Attempts, "--default-models")
foreach ($boss in $Area3Boss) { $arguments += @("--area3-boss", $boss) }
foreach ($boss in $Area5Boss) { $arguments += @("--area5-boss", $boss) }
if ($Guild) { $arguments += @("--guild", $Guild) }
if ($Execute) { $arguments += "--execute" }

$env:PYTHONPATH = "$Root;$(Join-Path $Root 'src')"
Push-Location $Root
try {
    & $python @arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
