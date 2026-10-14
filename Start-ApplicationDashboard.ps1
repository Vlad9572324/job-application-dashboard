$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Port = if ($env:HH_BOT_PORT) { $env:HH_BOT_PORT } else { "8000" }
$HostName = if ($env:HH_BOT_HOST) { $env:HH_BOT_HOST } else { "127.0.0.1" }
$UnsafeExpose = ($env:HH_BOT_UNSAFE_EXPOSE -match "^(1|true|yes)$")
$ExposeLan = $UnsafeExpose -and ($HostName -notin @("127.0.0.1", "localhost", "::1"))
$LocalHost = if ($HostName -eq "::") { "[::1]" } else { "127.0.0.1" }
$Url = "http://$LocalHost`:$Port"
$LogDir = Join-Path $Root "data"
$OutLog = Join-Path $LogDir "server.out.log"
$ErrLog = Join-Path $LogDir "server.err.log"
$ApiKeyFile = Join-Path $LogDir "hh_bot_api_key.txt"

if (-not (Test-Path $Python)) {
  Write-Host "Virtual environment not found. Creating .venv..."
  python -m venv (Join-Path $Root ".venv")
  & $Python -m pip install -r (Join-Path $Root "requirements.txt")
}

New-Item -ItemType Directory -Force $LogDir | Out-Null
if ($ExposeLan) {
  if (-not $env:HH_BOT_API_KEY) {
    if (-not (Test-Path -LiteralPath $ApiKeyFile)) {
      [guid]::NewGuid().ToString("N") | Set-Content -LiteralPath $ApiKeyFile -Encoding ASCII
    }
    $env:HH_BOT_API_KEY = (Get-Content -LiteralPath $ApiKeyFile -Raw).Trim()
  }
  if (-not $env:HH_BOT_API_KEY) {
    throw "HH_BOT_API_KEY is required when exposing the dashboard outside loopback."
  }
}
$AppUrl = if ($env:HH_BOT_API_KEY) { "$Url/?key=$($env:HH_BOT_API_KEY)" } else { $Url }

$existing = Get-CimInstance Win32_Process |
  Where-Object {
    ($_.ExecutablePath -like "$Root\.venv\Scripts\python.exe" -and $_.CommandLine -like "*web_app.py*")
  }

if (-not $existing) {
  Start-Process -FilePath $Python `
    -ArgumentList "web_app.py" `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog | Out-Null
}

$ready = $false
for ($i = 0; $i -lt 30; $i += 1) {
  try {
    $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 2
    if ($response.StatusCode -eq 200) {
      $ready = $true
      break
    }
  } catch {
    Start-Sleep -Seconds 1
  }
}

if ($ready) {
  Start-Process $AppUrl
  Write-Host "Application dashboard is running at $AppUrl"
  if ($ExposeLan) {
    $lanIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
      Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
      Select-Object -ExpandProperty IPAddress)
    foreach ($ip in $lanIps) {
      Write-Host "LAN IPv4 URL: http://$ip`:$Port/?key=$($env:HH_BOT_API_KEY)"
    }
    $lanIpv6s = @(Get-NetIPAddress -AddressFamily IPv6 -ErrorAction SilentlyContinue |
      Where-Object {
        $_.AddressState -eq "Preferred" -and
        $_.IPAddress -notlike "fe80:*" -and
        $_.IPAddress -notlike "*%*"
      } |
      Select-Object -ExpandProperty IPAddress)
    foreach ($ip in $lanIpv6s) {
      Write-Host "LAN IPv6 URL: http://[$ip]:$Port/?key=$($env:HH_BOT_API_KEY)"
    }
  }
} else {
  Write-Host "Application dashboard did not become ready. Check:"
  Write-Host $ErrLog
  exit 1
}
