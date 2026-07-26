param(
    [string]$OutputPath = "output\synthetic_test.wav"
)

$ErrorActionPreference = "Stop"
$packageRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $packageRoot "samples\test_scam_script.txt"

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Synthetic speech script not found: $scriptPath"
}

if ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
} else {
    $resolvedOutput = [System.IO.Path]::GetFullPath(
        (Join-Path $packageRoot $OutputPath)
    )
}

$outputDirectory = Split-Path -Parent $resolvedOutput
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$text = Get-Content -LiteralPath $scriptPath -Raw -Encoding UTF8

Add-Type -AssemblyName System.Speech
$synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer

try {
    $synthesizer.SetOutputToWaveFile($resolvedOutput)
    $synthesizer.Speak($text)
} finally {
    $synthesizer.Dispose()
}

Write-Output "Synthetic test audio created: $resolvedOutput"
Write-Output "This file is only for input smoke testing. Voice quality depends on installed Windows voices."
