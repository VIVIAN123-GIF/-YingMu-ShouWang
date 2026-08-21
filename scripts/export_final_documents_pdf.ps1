param(
    [string]$InputDir = "final-delivery\output\docx",
    [string]$OutputDir = "final-delivery\output\pdf",
    [string]$Soffice = "C:\Program Files\LibreOffice\program\soffice.com"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
if (-not (Test-Path -LiteralPath $Soffice)) {
    $command = Get-Command soffice -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "LibreOffice was not found. Install it or pass -Soffice."
    }
    $Soffice = $command.Source
}
$inputPath = (Resolve-Path -LiteralPath $InputDir).Path
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$outputPath = (Resolve-Path -LiteralPath $OutputDir).Path
$documents = @(Get-ChildItem -LiteralPath $inputPath -Filter "*.docx" -File | Sort-Object Name)
if ($documents.Count -lt 1) {
    throw "No DOCX files found in $inputPath."
}

$profilePath = Join-Path ([IO.Path]::GetTempPath()) ("yingmu-libreoffice-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $profilePath | Out-Null
$profileUri = ([Uri]$profilePath).AbsoluteUri
try {
    $arguments = @(
        "-env:UserInstallation=$profileUri",
        "--invisible",
        "--headless",
        "--norestore",
        "--convert-to", "pdf",
        "--outdir", $outputPath
    ) + @($documents.FullName)
    & $Soffice @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "LibreOffice PDF export failed with exit code $LASTEXITCODE."
    }
    $pdfs = @(Get-ChildItem -LiteralPath $outputPath -Filter "*.pdf" -File)
    foreach ($source in $documents) {
        $expected = Join-Path $outputPath ($source.BaseName + ".pdf")
        if (-not (Test-Path -LiteralPath $expected) -or (Get-Item -LiteralPath $expected).Length -eq 0) {
            throw "Expected PDF was not generated: $expected"
        }
        Write-Host "EXPORTED $expected"
    }
}
finally {
    $resolvedProfile = [IO.Path]::GetFullPath($profilePath)
    $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedProfile.StartsWith($resolvedTemp) -and [IO.Directory]::Exists($resolvedProfile)) {
        [IO.Directory]::Delete($resolvedProfile, $true)
    }
}
