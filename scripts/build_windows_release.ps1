param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$OutputRoot = "output\windows",
    [switch]$SkipFrontend,
    [switch]$SkipPyInstaller
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$productName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6JCk55uu5a6I5pyb"))
$runGuideName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6L+Q6KGM6K+05piO"))

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python runtime not found: $Python"
}
if (-not (Test-Path -LiteralPath "models\pose_landmarker_heavy.task")) {
    throw "MediaPipe model is missing. Run the documented model downloader first."
}
$requiredReleaseFiles = @(
    "adapters\trajectory_adapter.py",
    "backend\schemas\risk_review.py",
    "backend\service\stream_buffer_service.py",
    "backend\worker\stream_buffer_worker.py",
    "scene-calibrations\scene-living-room-v1.json",
    "scene-calibrations\scene-recorded-demo-v1.json"
)
foreach ($requiredFile in $requiredReleaseFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile)) {
        throw "Required release file is missing: $requiredFile"
    }
}

if (-not $SkipFrontend) {
    Push-Location "frontend"
    try {
        $env:VITE_API_BASE_URL = "/api/v1"
        $env:VITE_DATA_MODE = "auto"
        $env:VITE_RESIDENT_ID = "resident-mock-001"
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE." }
        npm test -- --run
        if ($LASTEXITCODE -ne 0) { throw "frontend tests failed with exit code $LASTEXITCODE." }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "frontend build failed with exit code $LASTEXITCODE." }
    }
    finally {
        Pop-Location
    }
} elseif (-not (Test-Path -LiteralPath "frontend\dist\index.html")) {
    throw "SkipFrontend requires an existing frontend production build."
}

if (-not $SkipPyInstaller) {
    & $Python -m pip install -r backend\requirements-release.txt
    if ($LASTEXITCODE -ne 0) { throw "Python release dependency installation failed with exit code $LASTEXITCODE." }
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --name YingMuShouWang `
        --collect-submodules backend `
        --collect-submodules contracts `
        --hidden-import aiosqlite `
        --hidden-import adapters.trajectory_adapter `
        --add-data "frontend\dist;frontend_dist" `
        --add-data "contracts\v1\rulesets;contracts\v1\rulesets" `
        --add-data "models\pose_landmarker_heavy.task;models" `
        scripts\yingmu_launcher.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
} elseif (-not (Test-Path -LiteralPath "dist\YingMuShouWang\YingMuShouWang.exe")) {
    throw "SkipPyInstaller requires an existing PyInstaller output directory."
}

$release = Join-Path $OutputRoot "$productName-Windows"
if (Test-Path -LiteralPath $release) {
    Remove-Item -LiteralPath $release -Recurse -Force
}
New-Item -ItemType Directory -Path $release | Out-Null
Copy-Item -Path "dist\YingMuShouWang\*" -Destination $release -Recurse
Copy-Item -LiteralPath "packaging\start-demo.cmd" -Destination $release
Copy-Item -LiteralPath "packaging\start-live.cmd" -Destination $release
Copy-Item -LiteralPath "packaging\THIRD_PARTY_NOTICES.txt" -Destination $release
New-Item -ItemType Directory -Path (Join-Path $release "config") | Out-Null
Copy-Item -LiteralPath "packaging\.env.example" -Destination (Join-Path $release "config\.env.example")
Copy-Item -LiteralPath "scene-calibrations" -Destination (Join-Path $release "scene-calibrations") -Recurse
Copy-Item -LiteralPath "models" -Destination (Join-Path $release "models") -Recurse
New-Item -ItemType Directory -Path (Join-Path $release "runtime\logs") -Force | Out-Null

$readmePdf = Get-ChildItem -LiteralPath "final-delivery\output\pdf" -Filter "03-*.pdf" | Select-Object -First 1
if ($null -ne $readmePdf) {
    Copy-Item -LiteralPath $readmePdf.FullName -Destination (Join-Path $release "README-$runGuideName.pdf")
}

$smokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("yingmu-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
$smokePassed = $false
try {
    & (Join-Path $release "YingMuShouWang.exe") self-check
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged self-check failed with exit code $LASTEXITCODE."
    }
    & (Join-Path $release "YingMuShouWang.exe") demo --host 127.0.0.1 --port 8099 --runtime-dir $smokeRoot --no-browser --smoke-test
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged demo stack failed its smoke test with exit code $LASTEXITCODE."
    }
    $smokePassed = $true
}
finally {
    $resolvedSmokeRoot = [System.IO.Path]::GetFullPath($smokeRoot)
    $resolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($smokePassed -and $resolvedSmokeRoot.StartsWith($resolvedTempRoot) -and (Test-Path -LiteralPath $resolvedSmokeRoot)) {
        Remove-Item -LiteralPath $resolvedSmokeRoot -Recurse -Force
    } elseif (-not $smokePassed) {
        Write-Warning "Packaged smoke logs retained at $resolvedSmokeRoot"
    }
}

$manifestPath = Join-Path $release "MANIFEST-SHA256.txt"
$releasePrefix = ([System.IO.Path]::GetFullPath($release)).TrimEnd("\") + "\"
$manifestLines = Get-ChildItem -LiteralPath $release -File -Recurse |
    Where-Object { $_.FullName -ne $manifestPath } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($releasePrefix.Length).Replace("\", "/")
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        "$hash  $relative"
    }
Set-Content -LiteralPath $manifestPath -Value $manifestLines -Encoding utf8

$zipPath = Join-Path $OutputRoot "$productName-Windows.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -LiteralPath $release -DestinationPath $zipPath -CompressionLevel Optimal

$freshRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("yingmu-windows-fresh-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $freshRoot | Out-Null
$freshPassed = $false
try {
    Expand-Archive -LiteralPath $zipPath -DestinationPath $freshRoot
    $freshExe = Get-ChildItem -LiteralPath $freshRoot -Filter "YingMuShouWang.exe" -File -Recurse
    if (@($freshExe).Count -ne 1) {
        throw "Fresh Windows ZIP must contain exactly one YingMuShouWang.exe."
    }
    $freshRelease = $freshExe[0].Directory.FullName
    $freshManifest = Join-Path $freshRelease "MANIFEST-SHA256.txt"
    if (-not (Test-Path -LiteralPath $freshManifest)) {
        throw "Fresh Windows ZIP is missing MANIFEST-SHA256.txt."
    }
    foreach ($line in Get-Content -LiteralPath $freshManifest -Encoding utf8) {
        if (-not $line) { continue }
        if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
            throw "Fresh Windows ZIP manifest contains an invalid line."
        }
        $expectedHash = $Matches[1]
        $relativePath = $Matches[2].Replace('/', '\')
        $manifestFile = Join-Path $freshRelease $relativePath
        if (-not (Test-Path -LiteralPath $manifestFile -PathType Leaf)) {
            throw "Fresh Windows ZIP manifest references a missing file."
        }
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestFile).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "Fresh Windows ZIP manifest hash mismatch."
        }
    }
    & $freshExe[0].FullName self-check
    if ($LASTEXITCODE -ne 0) {
        throw "Fresh Windows ZIP self-check failed with exit code $LASTEXITCODE."
    }
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $freshPort = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    $listener.Stop()
    $freshRuntime = Join-Path $freshRoot "runtime"
    & $freshExe[0].FullName demo --host 127.0.0.1 --port $freshPort --runtime-dir $freshRuntime --no-browser --smoke-test
    if ($LASTEXITCODE -ne 0) {
        throw "Fresh Windows ZIP demo smoke failed with exit code $LASTEXITCODE."
    }
    $freshPassed = $true
}
finally {
    $resolvedFreshRoot = [System.IO.Path]::GetFullPath($freshRoot)
    $resolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($freshPassed -and $resolvedFreshRoot.StartsWith($resolvedTempRoot) -and (Test-Path -LiteralPath $resolvedFreshRoot)) {
        Remove-Item -LiteralPath $resolvedFreshRoot -Recurse -Force
    } elseif (-not $freshPassed) {
        Write-Warning "Fresh Windows ZIP diagnostics retained at $resolvedFreshRoot"
    }
}
Write-Host "PASS: Windows release created at $zipPath"
