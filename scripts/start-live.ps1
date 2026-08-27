param(
    [string]$Config = 'C:\YingMu-private\live.env',
    [string]$BackendHost = '127.0.0.1',
    [int]$Port = 8000,
    [switch]$WithQuickTunnel,
    [string]$Cloudflared = 'cloudflared.exe'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment not found: $python"
}
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    throw "Live configuration not found: $Config"
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use"
}

Set-Location -LiteralPath $projectRoot
$launcherArgs = @(
    '-m', 'scripts.yingmu_launcher', 'live',
    '--config', $Config,
    '--host', $BackendHost,
    '--port', "$Port",
    '--no-browser'
)

Write-Host "Starting FastAPI, Alarm Worker, Agent Worker, and enabled Stream Buffer Worker..."
$backend = Start-Process -FilePath $python -ArgumentList $launcherArgs `
    -WorkingDirectory $projectRoot -PassThru -NoNewWindow

try {
    $healthUrl = "http://127.0.0.1:$Port/health"
    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
            if ($health.status -eq 'ok') { break }
        } catch {
            if ($backend.HasExited) { throw "Backend exited before health check passed" }
        }
    } while ((Get-Date) -lt $deadline)

    if (-not $health -or $health.status -ne 'ok') {
        throw "Local health check did not pass within 30 seconds"
    }
    Write-Host "Local API is healthy: $healthUrl"

    if ($WithQuickTunnel) {
        $tunnel = Get-Command $Cloudflared -ErrorAction SilentlyContinue
        if (-not $tunnel) {
            throw "cloudflared was not found. Install it or pass -Cloudflared with its full path."
        }
        Write-Host "Starting Quick Tunnel to http://127.0.0.1:$Port"
        Write-Host 'Keep this window open and use the https://*.trycloudflare.com URL printed by cloudflared.'
        & $tunnel.Source tunnel --url "http://127.0.0.1:$Port"
    } else {
        Write-Host 'Backend is running. Press Ctrl+C to stop the full stack.'
        Wait-Process -Id $backend.Id
    }
}
finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
