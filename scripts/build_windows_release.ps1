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
        --paths "deliverables\cym\audio-behavior-demo\src" `
        --collect-submodules backend `
        --collect-submodules contracts `
        --hidden-import aiosqlite `
        --hidden-import adapters.trajectory_adapter `
        --hidden-import adapters.language_adapter `
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
New-Item -ItemType Directory -Path (Join-Path $release "runtime\logs") -Force | Out-Null

$readmePdf = Get-ChildItem -LiteralPath "final-delivery\output\pdf" -Filter "03-*.pdf" | Select-Object -First 1
if ($null -ne $readmePdf) {
    Copy-Item -LiteralPath $readmePdf.FullName -Destination (Join-Path $release "README-$runGuideName.pdf")
}

$smokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("yingmu-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
$smokePassed = $false
try {
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
Write-Host "PASS: Windows release created at $zipPath"
