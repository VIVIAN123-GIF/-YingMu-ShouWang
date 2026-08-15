[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputVideo,
    [string]$Model = "models/pose_landmarker_heavy.task",
    [string]$OutputDir = "outputs/c6c_pose_review",
    [int]$MaxFrames = 0
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$inputPath = (Resolve-Path $InputVideo).Path
$modelPath = Join-Path $projectRoot $Model
$outputPath = Join-Path $projectRoot $OutputDir

if (-not (Test-Path -LiteralPath $modelPath)) {
    throw "Pose model not found: $modelPath`nRun: .\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/download_pose_model.py --output $Model"
}
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python"
}

$args = @(
    "deliverables/zy/pose-demo/scripts/run_pose_demo.py",
    "--input", $inputPath,
    "--model", $modelPath,
    "--output-dir", $outputPath
)
if ($MaxFrames -gt 0) { $args += @("--max-frames", $MaxFrames) }

Write-Host "Processing real C6c material: $inputPath"
& $python @args
if ($LASTEXITCODE -ne 0) { throw "C6c pose processing failed with exit code $LASTEXITCODE" }
Write-Host "Outputs written to: $outputPath"
