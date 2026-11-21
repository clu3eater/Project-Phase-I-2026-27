<#
.SYNOPSIS
    Start the demonstration copy of ASTRA on this computer -- the same copy the
    judges get from the hosted link.

.DESCRIPTION
    The four demo accounts are listed on the login screen (password sih2026),
    one aircraft starts signed off with a mission allotted to the operator, and
    account changes are refused. See layer4_core/demo.py.

    It runs on its OWN persistent data folder under your Windows profile, so
    its accounts, aircraft, missions, health and flight history survive a
    restart without touching the project's data\. On first start it imports
    an existing %TEMP%\astra-demo-run data folder if present. Run .\run.ps1
    once first: that sets up Python and builds the console.

    Listens on the local network and prints the Wi-Fi/LAN URLs. Connect the
    other device to the same Wi-Fi. Allow Python through Windows Firewall on
    Private networks if prompted. Use only on a trusted local network: demo
    passwords are public and this launcher serves HTTP.

.EXAMPLE
    .\run_demo.ps1
    .\run_demo.ps1 -Port 9000
#>
param([ValidateRange(1, 65535)][int]$Port = 8011)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py) -or -not (Test-Path (Join-Path $root 'layer5_viz\gcs_console\dist\index.html'))) {
    Write-Host 'Run .\run.ps1 once first: it sets up Python and builds the console.' -ForegroundColor Red
    exit 1
}

# Keep demo operations in an isolated, persistent location. The previous
# launcher recreated this folder on every start, erasing missions, saved
# health, twin wear and flight history. Migrate that old folder once without
# deleting it so the last run's records remain available.
$stateRoot = Join-Path $env:LOCALAPPDATA 'ASTRA\demo'
$dataDir = Join-Path $stateRoot 'data'
$legacyData = Join-Path (Join-Path $env:TEMP 'astra-demo-run') 'data'
if (-not (Test-Path $dataDir)) {
    New-Item -ItemType Directory -Force $stateRoot | Out-Null
    if (Test-Path $legacyData) {
        New-Item -ItemType Directory -Force $dataDir | Out-Null
        Get-ChildItem -LiteralPath $legacyData -Force |
            Copy-Item -Destination $dataDir -Recurse
        Write-Host "  Preserved existing demo records from $legacyData" -ForegroundColor Cyan
    }
}
New-Item -ItemType Directory -Force (Join-Path $dataDir 'synthetic') | Out-Null
foreach ($d in 'models', 'physics', 'terrain_tiles') {
    $src = Join-Path $root "data\$d"
    $dest = Join-Path $dataDir $d
    if ((Test-Path $src) -and -not (Test-Path $dest)) {
        Copy-Item -Recurse $src $dataDir
    }
}
foreach ($f in 'train.parquet', 'val.parquet', 'test.parquet', 'manifest.json') {
    $src = Join-Path $root "data\synthetic\$f"
    $dest = Join-Path $dataDir "synthetic\$f"
    if ((Test-Path $src) -and -not (Test-Path $dest)) {
        Copy-Item $src (Join-Path $dataDir 'synthetic')
    }
}

$env:DT_DEMO_MODE = '1'
$env:DT_DEMO_IDLE_RESET_MIN = '0'   # nothing here would restart it, so never exit
$env:DT_DATA_DIR = $dataDir
$env:DT_PERSIST = '1'
$env:DT_PORT = "$Port"
$env:DT_HOST = '0.0.0.0'
$env:DT_ALLOW_INSECURE_BIND = '1'  # explicit opt-in for the trusted LAN demo

$url = "http://127.0.0.1:$Port/"
Write-Host ''
Write-Host "  ASTRA demonstration copy:  $url" -ForegroundColor Green
Write-Host "  Saved missions, health and flight history:  $dataDir" -ForegroundColor Cyan
# Use .NET instead of Get-NetIPConfiguration, which requires CIM access.
# Prefer Wi-Fi; list other active LAN interfaces too for multi-adapter PCs.
$lanAddresses = @()
try {
    $adapters = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
        Where-Object {
            $_.OperationalStatus -eq 'Up' -and
            $_.NetworkInterfaceType -notin @('Loopback', 'Tunnel')
        } |
        Sort-Object @{Expression = { if ($_.NetworkInterfaceType -eq 'Wireless80211') { 0 } else { 1 } }}
    foreach ($adapter in $adapters) {
        foreach ($address in $adapter.GetIPProperties().UnicastAddresses) {
            $ip = $address.Address
            if ($ip.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
                -not [System.Net.IPAddress]::IsLoopback($ip) -and
                $ip.ToString() -notlike '169.254.*') {
                $lanAddresses += $ip.ToString()
                Write-Host "  Wi-Fi / LAN ($($adapter.Name)): http://$($ip):$Port/" -ForegroundColor Cyan
            }
        }
    }
} catch {
    Write-Warning 'Could not detect the LAN address. Run ipconfig and use http://<IPv4-address>:<port>/.'
}
if ($lanAddresses.Count -eq 0) {
    Write-Warning 'No LAN IPv4 address detected. Connect to Wi-Fi and run ipconfig to find your address.'
}
Write-Host '  Other devices: use a Wi-Fi / LAN URL above on the same network.'
Write-Host '  If blocked, allow Python through Windows Firewall on Private networks.'
Write-Host '  Logins are on the screen (password sih2026).  Ctrl+C to stop.'
Write-Host ''
# Open the browser once the server has had a moment to start.
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile -Command Start-Sleep 6; Start-Process '$url'"

Push-Location $root
try { & $py -m layer4_core.twin_api } finally { Pop-Location }
