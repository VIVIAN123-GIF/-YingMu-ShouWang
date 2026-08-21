param(
    [string]$PythonExe = "python",
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$versionText = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to run Python: $PythonExe"
}
$version = [version]$versionText.Trim()
if ($version -lt [version]"3.9" -or $version -ge [version]"3.13") {
    throw "Algorithm runtime requires Python 3.9-3.12; found $version"
}

if (-not (Test-Path (Join-Path $VenvPath "Scripts\python.exe"))) {
    & $PythonExe -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment" }
}

$venvPython = Join-Path $VenvPath "Scripts\python.exe"
$env:PYTHONUTF8 = "1"
$env:MPLCONFIGDIR = Join-Path $repoRoot ".cache\matplotlib"
New-Item -ItemType Directory -Path $env:MPLCONFIGDIR -Force | Out-Null

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip" }

& $venvPython -m pip install `
    -r backend\requirements.txt `
    -r contracts\requirements.txt `
    -r deliverables\zy\pose-demo\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Failed to install algorithm dependencies" }

$modelPath = Join-Path $repoRoot "models\pose_landmarker_heavy.task"
$modelTemp = "$modelPath.download"
$modelUrl = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
$expectedHash = "64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b"
$downloadModel = $true
if (Test-Path $modelPath) {
    $downloadModel = (Get-FileHash $modelPath -Algorithm SHA256).Hash.ToLower() -ne $expectedHash
}
if ($downloadModel) {
    Remove-Item -LiteralPath $modelTemp -Force -ErrorAction SilentlyContinue
    & $venvPython deliverables\zy\pose-demo\scripts\download_pose_model.py --output $modelTemp
    $downloaded = $LASTEXITCODE -eq 0

    # Some managed Windows networks block the system DNS resolver while allowing
    # public DNS. Keep TLS hostname verification and only override name resolution.
    if (-not $downloaded -and (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
        $addresses = @(
            Resolve-DnsName storage.googleapis.com -Server 8.8.8.8 -Type A -ErrorAction SilentlyContinue |
                Where-Object { $_.IPAddress -match '^\d+\.\d+\.\d+\.\d+$' } |
                Select-Object -ExpandProperty IPAddress -Unique
        )
        foreach ($address in $addresses) {
            & curl.exe -L --fail --connect-timeout 30 --max-time 300 `
                --resolve "storage.googleapis.com:443:$address" `
                -o $modelTemp $modelUrl
            if ($LASTEXITCODE -eq 0) {
                $downloaded = $true
                break
            }
        }
    }
    if (-not $downloaded -or -not (Test-Path $modelTemp)) {
        throw "Failed to download the pose model"
    }
    $downloadHash = (Get-FileHash $modelTemp -Algorithm SHA256).Hash.ToLower()
    if ($downloadHash -ne $expectedHash) {
        Remove-Item -LiteralPath $modelTemp -Force -ErrorAction SilentlyContinue
        throw "Downloaded pose model checksum mismatch: $downloadHash"
    }
    Move-Item -LiteralPath $modelTemp -Destination $modelPath -Force
}

$actualHash = (Get-FileHash $modelPath -Algorithm SHA256).Hash.ToLower()
if ($actualHash -ne $expectedHash) {
    throw "Pose model checksum mismatch: $actualHash"
}

& $venvPython deliverables\zy\pose-demo\scripts\verify_setup.py --model $modelPath
if ($LASTEXITCODE -ne 0) { throw "Algorithm runtime verification failed" }

Write-Output "Algorithm runtime is ready: $venvPython"
Write-Output "Pose model SHA256: $actualHash"
